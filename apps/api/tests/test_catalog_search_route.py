"""D1 /api/catalog/search 路由契约测试：q、content_type、tag、platform 筛选、别名匹配、无结果 suggestion、空查询 400。"""
import httpx
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
from cloudsite.services.catalog_search_projection import enqueue_catalog_search_outbox


_CATALOG_FTS_DDL = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS catalog_search_fts USING fts5("
    "entry_id UNINDEXED, content_type UNINDEXED, title, summary, description, "
    "aliases, tags, platforms, tokenize='unicode61 remove_diacritics 2')"
)


async def _bootstrap(tmp_path):
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)
        await conn.exec_driver_sql(_CATALOG_FTS_DDL)
    state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    index_factory = async_sessionmaker(index_engine, expire_on_commit=False)
    return state_engine, index_engine, state_factory, index_factory


async def _seed_user(state_factory):
    async with state_factory() as state:
        state.add(SystemSetting(key="setup_completed", value="true", value_type="string"))
        user = User(username="reader", username_normalized="reader", password_hash="x", status="active", created_at=utcnow(), updated_at=utcnow())
        state.add(user)
        await state.flush()
        _, user_token = await create_user_session(state, user.id, utcnow())
        await state.commit()
    return user_token


_ROOTS = {
    "software": (1, "/public"),
    "image": (2, "/images"),
}


async def _seed_entry(state, index, *, entry_id, slug, title, summary, content_type="software", platform="windows", tag_slug=None, revision=1):
    root_id, root_path = _ROOTS[content_type]
    state.add(ContentRootMapping(id=root_id, content_type=content_type, display_name=content_type.capitalize(), alist_path=root_path, enabled=True))
    state.add(CatalogEntry(entry_id=entry_id, content_type=content_type, slug=slug, title=title, summary=summary, status="published", revision=revision))
    state.add(CatalogRelease(release_id="cr_" + entry_id[-1], entry_id=entry_id, slug="2.0", title="2.0 Stable", channel="stable", status="published"))
    state.add(CatalogAsset(asset_id="ca_" + entry_id[-1], release_id="cr_" + entry_id[-1], slug=f"{slug}-asset", display_name=f"{title} Asset", platform=platform, architecture="arm64", package_type="portable"))
    rid = "res-" + entry_id[-1]
    state.add(CatalogLocation(location_id="cl_" + entry_id[-1], asset_id="ca_" + entry_id[-1], resource_id=rid, root_mapping_id=root_id, status="active"))
    if tag_slug:
        state.add(CatalogTag(tag_id="ct_" + tag_slug, slug=tag_slug, display_name=tag_slug.capitalize()))
        state.add(CatalogTagAssignment(tag_id="ct_" + tag_slug, target_type="entry", target_id=entry_id))
    index.add(Resource(id=rid, root_mapping_id=root_id, name=f"{slug}.zip", path=f"{root_path}/{slug}.zip", content_type=content_type, status="active"))
    await enqueue_catalog_search_outbox(state, entry_id=entry_id, revision=revision, action="upsert")


def _patch_sessions(monkeypatch, state_factory, index_factory):
    monkeypatch.setattr(main, "StateSession", state_factory)
    monkeypatch.setattr(main, "IndexSession", index_factory)
    monkeypatch.setattr(auth, "StateSession", state_factory)


async def _search(client, query, **params):
    qs = f"q={query}"
    for key, value in params.items():
        if value is not None:
            qs += f"&{key}={value}"
    return await client.get(f"/api/catalog/search?{qs}")


async def test_catalog_search_route_filters_by_query_content_type_tag_platform(tmp_path, monkeypatch):
    state_engine, index_engine, state_factory, index_factory = await _bootstrap(tmp_path)
    user_token = await _seed_user(state_factory)
    async with state_factory() as state, index_factory() as index:
        await _seed_entry(state, index, entry_id="ce_a", slug="toolbox", title="Toolbox", summary="Network toolkit", tag_slug="network", platform="windows")
        await _seed_entry(state, index, entry_id="ce_b", slug="imager", title="Imager", summary="Image editor", content_type="image", platform="cross", tag_slug="design")
        await state.commit()
        await index.commit()
    _patch_sessions(monkeypatch, state_factory, index_factory)

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(USER_SESSION_COOKIE, user_token)

        all_result = await _search(client, "Toolbox")
        assert all_result.status_code == 200, all_result.text
        assert all_result.json()["total"] == 1
        assert all_result.json()["items"][0]["entry_id"] == "ce_a"

        sw = await _search(client, "Toolbox", type="software")
        assert sw.json()["total"] == 1
        img = await _search(client, "Imager", type="image")
        assert img.json()["total"] == 1
        assert img.json()["items"][0]["entry_id"] == "ce_b"

        tagged = await _search(client, "Toolbox", tag="network")
        assert tagged.json()["total"] == 1
        tagged_none = await _search(client, "Toolbox", tag="design")
        assert tagged_none.json()["total"] == 0

        plat = await _search(client, "Toolbox", platform="windows")
        assert plat.json()["total"] == 1
        plat_none = await _search(client, "Toolbox", platform="linux")
        assert plat_none.json()["total"] == 0

    await state_engine.dispose()
    await index_engine.dispose()


async def test_catalog_search_route_alias_match_and_no_result_suggestion(tmp_path, monkeypatch):
    state_engine, index_engine, state_factory, index_factory = await _bootstrap(tmp_path)
    user_token = await _seed_user(state_factory)
    async with state_factory() as state, index_factory() as index:
        await _seed_entry(state, index, entry_id="ce_a", slug="toolbox", title="Toolbox", summary="Network toolkit")
        await state.commit()
        await index.commit()
    _patch_sessions(monkeypatch, state_factory, index_factory)

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(USER_SESSION_COOKIE, user_token)

        alias_slug = await _search(client, "toolbox-asset")
        assert alias_slug.status_code == 200, alias_slug.text
        assert alias_slug.json()["total"] == 1

        alias_display = await _search(client, "Toolbox Asset")
        assert alias_display.json()["total"] == 1

        no_result = await _search(client, "zzz-not-exist")
        assert no_result.status_code == 200, no_result.text
        payload = no_result.json()
        assert payload["total"] == 0
        assert payload["items"] == []
        assert payload["suggestion"] is not None

    await state_engine.dispose()
    await index_engine.dispose()


async def test_catalog_search_route_rejects_empty_query(tmp_path, monkeypatch):
    state_engine, index_engine, state_factory, index_factory = await _bootstrap(tmp_path)
    user_token = await _seed_user(state_factory)
    _patch_sessions(monkeypatch, state_factory, index_factory)

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(USER_SESSION_COOKIE, user_token)
        empty = await client.get("/api/search?q=")
        assert empty.status_code == 400
        assert empty.json()["detail"]["code"] == "SRCH-001"

        blank = await client.get("/api/catalog/search?q=   ")
        assert blank.status_code == 400
        assert blank.json()["detail"]["code"] == "CATALOG_SEARCH_INVALID"

    await state_engine.dispose()
    await index_engine.dispose()
