"""D1 catalog 搜索投影一致性端到端测试。

覆盖 TASK.md 交付 1：
- outbox 入队→消费→FTS 可搜（HTTP 路由全链路）
- 崩溃重放幂等（重复消费不重复插入）
- 旧 revision 不覆盖新数据（entry.revision > outbox.revision 跳过）
- 全量重建后人工条目可搜
- 权限过滤不依赖异步 FTS 删除：禁用条目后立即搜不到（fail-closed 实时校验）
- 旧 /api/search 契约零改动（返回旧文件结果，不含 catalog 条目）

通过 httpx ASGITransport 走真实 FastAPI 路由，monkeypatch main.StateSession/
IndexSession 指向临时 sqlite engine，复用 test_catalog_search_service.py 的
_bootstrap 模式直接构造 DB 状态。
"""
import httpx
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import auth, main
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
    SystemSetting,
    User,
    utcnow,
)
from cloudsite.sessions import USER_SESSION_COOKIE, create_user_session
from cloudsite.services.catalog_search_projection import (
    enqueue_catalog_search_outbox,
    rebuild_catalog_search_index,
)


_CATALOG_FTS_DDL = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS catalog_search_fts USING fts5("
    "entry_id UNINDEXED, content_type UNINDEXED, title, summary, description, "
    "aliases, tags, platforms, tokenize='unicode61 remove_diacritics 2')"
)
_SEARCH_FTS_DDL = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5("
    "object_id UNINDEXED, object_type UNINDEXED, name, extension, "
    "content_type UNINDEXED, description, tags, breadcrumb_text, tokenize='unicode61 remove_diacritics 2')"
)


async def _bootstrap(tmp_path):
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)
        await conn.exec_driver_sql(_CATALOG_FTS_DDL)
        await conn.exec_driver_sql(_SEARCH_FTS_DDL)
    state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    index_factory = async_sessionmaker(index_engine, expire_on_commit=False)
    return state_engine, index_engine, state_factory, index_factory


async def _seed_user(state_factory):
    """创建一个 active user + 有效会话，返回 cookie token。"""
    async with state_factory() as state:
        state.add(SystemSetting(key="setup_completed", value="true", value_type="string"))
        user = User(
            username="reader",
            username_normalized="reader",
            password_hash="x",
            status="active",
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        state.add(user)
        await state.flush()
        _, user_token = await create_user_session(state, user.id, utcnow())
        await state.commit()
    return user_token


async def _seed_published_entry(
    state,
    *,
    entry_id="ce_a",
    slug="toolbox",
    title="Toolbox",
    summary="Network toolkit",
    revision=1,
    tag_slug=None,
    platform="windows",
    resource_id=None,
):
    state.add(ContentRootMapping(id=1, content_type="software", display_name="Public", alist_path="/public", enabled=True))
    state.add(CatalogEntry(entry_id=entry_id, content_type="software", slug=slug, title=title, summary=summary, status="published", revision=revision))
    state.add(CatalogRelease(release_id="cr_" + entry_id[-1], entry_id=entry_id, slug="2.0", title="2.0 Stable", channel="stable", status="published"))
    state.add(CatalogAsset(asset_id="ca_" + entry_id[-1], release_id="cr_" + entry_id[-1], slug="win-arm64", display_name="Toolbox ARM64", platform=platform, architecture="arm64", package_type="portable"))
    rid = resource_id or ("res-" + entry_id[-1])
    state.add(CatalogLocation(location_id="cl_" + entry_id[-1], asset_id="ca_" + entry_id[-1], resource_id=rid, root_mapping_id=1, status="active"))
    if tag_slug:
        state.add(CatalogTag(tag_id="ct_" + tag_slug, slug=tag_slug, display_name=tag_slug.capitalize()))
        state.add(CatalogTagAssignment(tag_id="ct_" + tag_slug, target_type="entry", target_id=entry_id))
    return rid


async def _seed_resource(index, *, resource_id="res-a", root_mapping_id=1, content_type="software", status="active", name="toolbox.zip"):
    index.add(Resource(id=resource_id, root_mapping_id=root_mapping_id, name=name, path=f"/public/{name}", content_type=content_type, status=status))


def _patch_sessions(monkeypatch, state_factory, index_factory):
    monkeypatch.setattr(main, "StateSession", state_factory)
    monkeypatch.setattr(main, "IndexSession", index_factory)
    monkeypatch.setattr(auth, "StateSession", state_factory)


async def _search_catalog(client, query, **params):
    qs = f"q={query}"
    for key, value in params.items():
        if value is not None:
            qs += f"&{key}={value}"
    response = await client.get(f"/api/catalog/search?{qs}")
    assert response.status_code == 200, response.text
    return response.json()


async def test_e2e_outbox_enqueue_consume_fts_searchable(tmp_path, monkeypatch):
    """admin 写入 published entry + outbox 后，/api/catalog/search 全链路可搜。"""
    state_engine, index_engine, state_factory, index_factory = await _bootstrap(tmp_path)
    user_token = await _seed_user(state_factory)
    async with state_factory() as state, index_factory() as index:
        rid = await _seed_published_entry(state, tag_slug="network")
        await _seed_resource(index, resource_id=rid)
        await enqueue_catalog_search_outbox(state, entry_id="ce_a", revision=1, action="upsert")
        await state.commit()
        await index.commit()
    _patch_sessions(monkeypatch, state_factory, index_factory)

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(USER_SESSION_COOKIE, user_token)
        result = await _search_catalog(client, "Toolbox")
        assert result["total"] == 1
        assert result["items"][0]["entry_id"] == "ce_a"
        assert result["items"][0]["availability"] == "available"

        tagged = await _search_catalog(client, "network", tag="network")
        assert tagged["total"] == 1

        aliased = await _search_catalog(client, "win-arm64")
        assert aliased["total"] == 1

    await state_engine.dispose()
    await index_engine.dispose()


async def test_e2e_outbox_replay_idempotent_via_search(tmp_path, monkeypatch):
    """崩溃重放：重置 consumed_at 后再次搜索，结果不重复、不丢失。"""
    state_engine, index_engine, state_factory, index_factory = await _bootstrap(tmp_path)
    user_token = await _seed_user(state_factory)
    async with state_factory() as state, index_factory() as index:
        rid = await _seed_published_entry(state)
        await _seed_resource(index, resource_id=rid)
        await enqueue_catalog_search_outbox(state, entry_id="ce_a", revision=1, action="upsert")
        await state.commit()
        await index.commit()
    _patch_sessions(monkeypatch, state_factory, index_factory)

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(USER_SESSION_COOKIE, user_token)
        first = await _search_catalog(client, "Toolbox")
        assert first["total"] == 1

    async with state_factory() as state:
        await state.execute(update(CatalogSearchOutbox).values(consumed_at=None))
        await state.commit()

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(USER_SESSION_COOKIE, user_token)
        replayed = await _search_catalog(client, "Toolbox")
        assert replayed["total"] == 1
        assert replayed["items"][0]["entry_id"] == "ce_a"

    await state_engine.dispose()
    await index_engine.dispose()


async def test_e2e_old_revision_does_not_overwrite_newer(tmp_path, monkeypatch):
    """旧 revision outbox 行在 entry 已推进到更高 revision 后被跳过。"""
    state_engine, index_engine, state_factory, index_factory = await _bootstrap(tmp_path)
    user_token = await _seed_user(state_factory)
    async with state_factory() as state, index_factory() as index:
        rid = await _seed_published_entry(state, title="Old Title")
        await _seed_resource(index, resource_id=rid)
        await enqueue_catalog_search_outbox(state, entry_id="ce_a", revision=1, action="upsert")
        await state.commit()
        entry = await state.get(CatalogEntry, "ce_a")
        entry.title = "New Title"
        entry.revision = 2
        await enqueue_catalog_search_outbox(state, entry_id="ce_a", revision=2, action="upsert")
        await state.commit()
        await index.commit()
    _patch_sessions(monkeypatch, state_factory, index_factory)

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(USER_SESSION_COOKIE, user_token)
        new_result = await _search_catalog(client, "New Title")
        assert new_result["total"] == 1
        old_result = await _search_catalog(client, "Old Title")
        assert old_result["total"] == 0

    await state_engine.dispose()
    await index_engine.dispose()


async def test_e2e_rebuild_restores_manual_entry_searchable(tmp_path, monkeypatch):
    """FTS 损坏后全量重建，人工条目元数据仍可搜。"""
    state_engine, index_engine, state_factory, index_factory = await _bootstrap(tmp_path)
    user_token = await _seed_user(state_factory)
    async with state_factory() as state, index_factory() as index:
        rid = await _seed_published_entry(state, tag_slug="network")
        await _seed_resource(index, resource_id=rid)
        await enqueue_catalog_search_outbox(state, entry_id="ce_a", revision=1, action="upsert")
        await state.commit()
        await index.commit()
    _patch_sessions(monkeypatch, state_factory, index_factory)

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(USER_SESSION_COOKIE, user_token)
        before = await _search_catalog(client, "Toolbox")
        assert before["total"] == 1

    async with index_factory() as index:
        await index.execute(text("DELETE FROM catalog_search_fts"))
        await index.commit()

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(USER_SESSION_COOKIE, user_token)
        broken = await _search_catalog(client, "Toolbox")
        assert broken["total"] == 0

    async with state_factory() as state, index_factory() as index:
        count = await rebuild_catalog_search_index(state, index)
        assert count >= 1

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(USER_SESSION_COOKIE, user_token)
        rebuilt = await _search_catalog(client, "Toolbox")
        assert rebuilt["total"] == 1
        assert rebuilt["items"][0]["entry_id"] == "ce_a"

    await state_engine.dispose()
    await index_engine.dispose()


async def test_e2e_fail_closed_disable_entry_immediately_unsearchable(tmp_path, monkeypatch):
    """禁用条目后立即搜不到，不依赖异步 FTS 删除（fail-closed 实时校验）。"""
    state_engine, index_engine, state_factory, index_factory = await _bootstrap(tmp_path)
    user_token = await _seed_user(state_factory)
    async with state_factory() as state, index_factory() as index:
        rid = await _seed_published_entry(state)
        await _seed_resource(index, resource_id=rid)
        await enqueue_catalog_search_outbox(state, entry_id="ce_a", revision=1, action="upsert")
        await state.commit()
        await index.commit()
    _patch_sessions(monkeypatch, state_factory, index_factory)

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(USER_SESSION_COOKIE, user_token)
        before = await _search_catalog(client, "Toolbox")
        assert before["total"] == 1

    async with state_factory() as state:
        entry = await state.get(CatalogEntry, "ce_a")
        entry.status = "draft"
        entry.revision = entry.revision + 1
        await state.commit()

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(USER_SESSION_COOKIE, user_token)
        after = await _search_catalog(client, "Toolbox")
        assert after["total"] == 0
        assert after["suggestion"] is not None

    await state_engine.dispose()
    await index_engine.dispose()


async def test_e2e_fail_closed_disabled_root_immediately_unsearchable(tmp_path, monkeypatch):
    """location 指向禁用 root 时 fail-closed 丢弃，不依赖 FTS 删除。"""
    state_engine, index_engine, state_factory, index_factory = await _bootstrap(tmp_path)
    user_token = await _seed_user(state_factory)
    async with state_factory() as state, index_factory() as index:
        state.add(ContentRootMapping(id=1, content_type="software", display_name="Public", alist_path="/public", enabled=True))
        state.add(ContentRootMapping(id=2, content_type="software", display_name="Private", alist_path="/private", enabled=True))
        state.add(CatalogEntry(entry_id="ce_a", content_type="software", slug="toolbox", title="Toolbox", summary="Network toolkit", status="published", revision=1))
        state.add(CatalogRelease(release_id="cr_a", entry_id="ce_a", slug="2.0", title="2.0 Stable", channel="stable", status="published"))
        state.add(CatalogAsset(asset_id="ca_a", release_id="cr_a", slug="win-arm64", display_name="Toolbox ARM64", platform="windows", architecture="arm64", package_type="portable"))
        state.add(CatalogLocation(location_id="cl_a", asset_id="ca_a", resource_id="res-a", root_mapping_id=2, status="active"))
        await _seed_resource(index, resource_id="res-a", root_mapping_id=2)
        await enqueue_catalog_search_outbox(state, entry_id="ce_a", revision=1, action="upsert")
        await state.commit()
        await index.commit()
    _patch_sessions(monkeypatch, state_factory, index_factory)

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(USER_SESSION_COOKIE, user_token)
        before = await _search_catalog(client, "Toolbox")
        assert before["total"] == 1

    async with state_factory() as state:
        await state.execute(update(ContentRootMapping).where(ContentRootMapping.id == 2).values(enabled=False))
        await state.commit()

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(USER_SESSION_COOKIE, user_token)
        after = await _search_catalog(client, "Toolbox")
        assert after["total"] == 0

    await state_engine.dispose()
    await index_engine.dispose()


async def test_e2e_legacy_search_contract_excludes_catalog_entries(tmp_path, monkeypatch):
    """旧 /api/search 契约零改动：返回旧文件结果，不含 catalog 条目。"""
    state_engine, index_engine, state_factory, index_factory = await _bootstrap(tmp_path)
    user_token = await _seed_user(state_factory)
    async with state_factory() as state, index_factory() as index:
        rid = await _seed_published_entry(state, title="Catalog Only Title")
        await _seed_resource(index, resource_id=rid, name="catalog-only.zip")
        await enqueue_catalog_search_outbox(state, entry_id="ce_a", revision=1, action="upsert")
        index.add(Resource(id="res-file-1", root_mapping_id=1, name="legacy-toolbox.zip", path="/public/legacy-toolbox.zip", content_type="software", status="active", extension="zip", size=100))
        await index.execute(text(
            "INSERT INTO search_fts(object_id, object_type, name, extension, content_type, description, tags, breadcrumb_text) "
            "VALUES ('res-file-1', 'resource', 'legacy-toolbox.zip', 'zip', 'software', '', '', '/public')"
        ))
        await state.commit()
        await index.commit()
    _patch_sessions(monkeypatch, state_factory, index_factory)

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(USER_SESSION_COOKIE, user_token)
        response = await client.get("/api/search?q=toolbox")
        assert response.status_code == 200, response.text
        payload = response.json()
        ids = [item["id"] for item in payload["items"]]
        assert "res-file-1" in ids
        assert "ce_a" not in ids
        for item in payload["items"]:
            assert item["object_type"] in {"resource", "folder"}

        catalog_only = await client.get("/api/search?q=Catalog Only Title")
        assert catalog_only.status_code == 200, catalog_only.text
        assert catalog_only.json()["total"] == 0

    await state_engine.dispose()
    await index_engine.dispose()
