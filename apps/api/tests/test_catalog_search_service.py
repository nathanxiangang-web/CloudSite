"""D1 catalog 资源级检索服务测试：FTS 投影、outbox 消费、fail-closed、别名/平台/标签过滤、无结果反馈。"""
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.database import IndexBase, StateBase
from cloudsite.models import (
    CatalogAsset,
    CatalogEntry,
    CatalogLocation,
    CatalogRelease,
    CatalogSearchOutbox,
    CatalogTag,
    CatalogTagAssignment,
    ContentRootMapping,
    Resource,
)
from cloudsite.services.catalog_search import search_published_catalog
from cloudsite.services.catalog_search_projection import (
    consume_catalog_search_outbox,
    enqueue_catalog_search_outbox,
    rebuild_catalog_search_index,
)


async def _bootstrap(tmp_path):
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)
        await conn.exec_driver_sql(
            "CREATE VIRTUAL TABLE IF NOT EXISTS catalog_search_fts USING fts5("
            "entry_id UNINDEXED, content_type UNINDEXED, title, summary, description, "
            "aliases, tags, platforms, tokenize='unicode61 remove_diacritics 2')"
        )
    state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    index_factory = async_sessionmaker(index_engine, expire_on_commit=False)
    return state_engine, index_engine, state_factory, index_factory


async def _seed_published_entry(state, *, entry_id="ce_a", slug="toolbox", title="Toolbox", summary="Network toolkit", tag_slug=None, platform="windows"):
    state.add(ContentRootMapping(id=1, content_type="software", display_name="Public", alist_path="/public", enabled=True))
    state.add(CatalogEntry(entry_id=entry_id, content_type="software", slug=slug, title=title, summary=summary, status="published", revision=1))
    state.add(CatalogRelease(release_id="cr_" + entry_id[-1], entry_id=entry_id, slug="2.0", title="2.0 Stable", channel="stable", status="published"))
    state.add(CatalogAsset(asset_id="ca_" + entry_id[-1], release_id="cr_" + entry_id[-1], slug="win-arm64", display_name="Toolbox ARM64", platform=platform, architecture="arm64", package_type="portable"))
    state.add(CatalogLocation(location_id="cl_" + entry_id[-1], asset_id="ca_" + entry_id[-1], resource_id="res-" + entry_id[-1], root_mapping_id=1, status="active"))
    if tag_slug:
        state.add(CatalogTag(tag_id="ct_" + tag_slug, slug=tag_slug, display_name=tag_slug.capitalize()))
        state.add(CatalogTagAssignment(tag_id="ct_" + tag_slug, target_type="entry", target_id=entry_id))


async def _seed_resource(index, *, resource_id="res-a", root_mapping_id=1, content_type="software", status="active"):
    index.add(Resource(id=resource_id, root_mapping_id=root_mapping_id, name="toolbox.zip", path="/public/toolbox.zip", content_type=content_type, status=status))


async def test_catalog_search_uses_fts_projection_and_filters_live_scope(tmp_path):
    state_engine, index_engine, state_factory, index_factory = await _bootstrap(tmp_path)
    async with state_factory() as state, index_factory() as index:
        await _seed_published_entry(state, tag_slug="network")
        await _seed_resource(index)
        await state.commit()
        await index.commit()
        # 模拟业务写操作入队 outbox
        await enqueue_catalog_search_outbox(state, entry_id="ce_a", revision=1, action="upsert")
        await state.commit()
        # 搜索前消费 outbox
        stats = await consume_catalog_search_outbox(state, index)
        assert stats["consumed"] == 1

        result = await search_published_catalog(state, index, query="network", tag="network", platform="windows")
        assert result["total"] == 1
        assert result["items"][0]["entry_id"] == "ce_a"
        assert result["items"][0]["match_type"] == "metadata"

        exact = await search_published_catalog(state, index, query="Toolbox")
        assert exact["items"][0]["match_type"] == "exact"

        alias = await search_published_catalog(state, index, query="win-arm64")
        assert alias["total"] == 1  # 别名（asset slug）匹配

    await state_engine.dispose()
    await index_engine.dispose()


async def test_catalog_search_fail_closed_when_location_unavailable(tmp_path):
    state_engine, index_engine, state_factory, index_factory = await _bootstrap(tmp_path)
    async with state_factory() as state, index_factory() as index:
        await _seed_published_entry(state, entry_id="ce_hidden", slug="hidden-tool", title="Hidden Tool")
        # location 指向 disabled root（root_mapping_id=2 未启用）
        state.add(CatalogLocation(location_id="cl_h2", asset_id="ca_h", resource_id="res-hidden", root_mapping_id=2, status="active"))
        await _seed_resource(index, resource_id="res-hidden")
        await state.commit()
        await index.commit()
        await enqueue_catalog_search_outbox(state, entry_id="ce_hidden", revision=1, action="upsert")
        await state.commit()
        await consume_catalog_search_outbox(state, index)

        # FTS 中有条目，但实时校验 availability 不可用，fail-closed 丢弃
        result = await search_published_catalog(state, index, query="Hidden Tool")
        assert result["total"] == 0
        assert result["suggestion"] is not None

    await state_engine.dispose()
    await index_engine.dispose()


async def test_catalog_search_outbox_replay_is_idempotent(tmp_path):
    """崩溃重放：consumed_at 被重置后再次消费不重复写入、不破坏结果。"""
    state_engine, index_engine, state_factory, index_factory = await _bootstrap(tmp_path)
    async with state_factory() as state, index_factory() as index:
        await _seed_published_entry(state)
        await _seed_resource(index)
        await state.commit()
        await index.commit()
        await enqueue_catalog_search_outbox(state, entry_id="ce_a", revision=1, action="upsert")
        await state.commit()
        first = await consume_catalog_search_outbox(state, index)
        assert first["consumed"] == 1

        # 模拟崩溃：重置 consumed_at，重放
        from sqlalchemy import update
        await state.execute(update(CatalogSearchOutbox).values(consumed_at=None))
        await state.commit()
        replay = await consume_catalog_search_outbox(state, index)
        # 水位保护：applied_revision >= outbox.revision，跳过
        assert replay["skipped"] == 1
        assert replay["consumed"] == 0

        result = await search_published_catalog(state, index, query="Toolbox")
        assert result["total"] == 1

    await state_engine.dispose()
    await index_engine.dispose()


async def test_catalog_search_old_revision_does_not_overwrite_newer(tmp_path):
    """旧 revision outbox 行在 entry 已推进到更高 revision 后被跳过。"""
    state_engine, index_engine, state_factory, index_factory = await _bootstrap(tmp_path)
    async with state_factory() as state, index_factory() as index:
        await _seed_published_entry(state, title="Old Title")
        await _seed_resource(index)
        await state.commit()
        await index.commit()
        # 旧 revision 入队但未消费
        await enqueue_catalog_search_outbox(state, entry_id="ce_a", revision=1, action="upsert")
        await state.commit()
        # entry 推进到 revision 2（标题更新）
        entry = await state.get(CatalogEntry, "ce_a")
        entry.title = "New Title"
        entry.revision = 2
        await enqueue_catalog_search_outbox(state, entry_id="ce_a", revision=2, action="upsert")
        await state.commit()
        stats = await consume_catalog_search_outbox(state, index)
        # 旧行被跳过（entry.revision=2 > outbox.revision=1），新行被消费
        assert stats["skipped"] == 1
        assert stats["consumed"] == 1

        # 搜索新标题命中，旧标题不命中
        assert (await search_published_catalog(state, index, query="New Title"))["total"] == 1
        assert (await search_published_catalog(state, index, query="Old Title"))["total"] == 0

    await state_engine.dispose()
    await index_engine.dispose()


async def test_catalog_search_rebuild_restores_projection(tmp_path):
    """索引重建后人工条目元数据仍可搜。"""
    state_engine, index_engine, state_factory, index_factory = await _bootstrap(tmp_path)
    async with state_factory() as state, index_factory() as index:
        await _seed_published_entry(state, tag_slug="network")
        await _seed_resource(index)
        await state.commit()
        await index.commit()
        await enqueue_catalog_search_outbox(state, entry_id="ce_a", revision=1, action="upsert")
        await state.commit()
        await consume_catalog_search_outbox(state, index)
        # 模拟 FTS 被清空（损坏）
        from sqlalchemy import text
        await index.execute(text("DELETE FROM catalog_search_fts"))
        await index.commit()
        assert (await search_published_catalog(state, index, query="Toolbox"))["total"] == 0

        # 重建
        count = await rebuild_catalog_search_index(state, index)
        assert count >= 1
        result = await search_published_catalog(state, index, query="Toolbox")
        assert result["total"] == 1

    await state_engine.dispose()
    await index_engine.dispose()


async def test_catalog_search_rejects_empty_query(tmp_path):
    state_engine, index_engine, state_factory, index_factory = await _bootstrap(tmp_path)
    async with state_factory() as state, index_factory() as index:
        try:
            await search_published_catalog(state, index, query="   ")
        except ValueError as exc:
            assert "empty" in str(exc)
        else:
            raise AssertionError("empty Catalog query must be rejected")
    await state_engine.dispose()
    await index_engine.dispose()


async def test_catalog_search_no_result_returns_suggestion(tmp_path):
    state_engine, index_engine, state_factory, index_factory = await _bootstrap(tmp_path)
    async with state_factory() as state, index_factory() as index:
        await _seed_published_entry(state)
        await _seed_resource(index)
        await state.commit()
        await index.commit()
        await enqueue_catalog_search_outbox(state, entry_id="ce_a", revision=1, action="upsert")
        await state.commit()
        await consume_catalog_search_outbox(state, index)
        result = await search_published_catalog(state, index, query="zzz-not-exist")
        assert result["total"] == 0
        assert result["suggestion"] is not None
        assert result["items"] == []
    await state_engine.dispose()
    await index_engine.dispose()


async def test_catalog_search_content_type_filter(tmp_path):
    state_engine, index_engine, state_factory, index_factory = await _bootstrap(tmp_path)
    async with state_factory() as state, index_factory() as index:
        await _seed_published_entry(state, entry_id="ce_sw", slug="sw-entry", title="Software Entry")
        await _seed_resource(index, resource_id="res-w")
        state.add(CatalogEntry(entry_id="ce_img", content_type="image", slug="img-entry", title="Image Entry", status="published", revision=1))
        state.add(CatalogRelease(release_id="cr_img", entry_id="ce_img", slug="unversioned", title="Default", status="published"))
        state.add(CatalogAsset(asset_id="ca_img", release_id="cr_img", slug="img-asset", display_name="Image Asset", platform="any"))
        state.add(CatalogLocation(location_id="cl_img", asset_id="ca_img", resource_id="res-img", root_mapping_id=1, status="active"))
        state.add(ContentRootMapping(id=2, content_type="image", display_name="Images", alist_path="/img", enabled=True))
        index.add(Resource(id="res-img", root_mapping_id=2, name="img.png", path="/img/img.png", content_type="image", status="active"))
        await state.commit()
        await index.commit()
        await enqueue_catalog_search_outbox(state, entry_id="ce_sw", revision=1, action="upsert")
        await enqueue_catalog_search_outbox(state, entry_id="ce_img", revision=1, action="upsert")
        await state.commit()
        await consume_catalog_search_outbox(state, index)
        # FTS content_type 过滤：仅 software 命中
        sw = await search_published_catalog(state, index, query="Entry", content_type="software")
        assert sw["total"] == 1
        assert sw["items"][0]["entry_id"] == "ce_sw"
        img = await search_published_catalog(state, index, query="Entry", content_type="image")
        assert img["total"] == 1
        assert img["items"][0]["entry_id"] == "ce_img"
    await state_engine.dispose()
    await index_engine.dispose()
