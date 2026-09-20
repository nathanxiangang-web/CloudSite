"""M5 首页热门排序修复与全类型入口测试。

覆盖：
1. schema v15->v16 迁移添加 popular_strategy/home_order/featured 列，幂等。
2. /api/home 返回 type_entries 与 popular_strategy，popular 不再按 size 排序。
3. /api/browse 全类型浏览路由返回正确结构，支持 type 筛选与排序。
"""
import httpx
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import auth, database, main
from cloudsite.database import IndexBase, StateBase
from cloudsite.migrations import CURRENT_SCHEMA_VERSION, get_state_schema_version
from cloudsite.models import ContentRootMapping, Resource, SiteSettings, SystemSetting, User, utcnow
from cloudsite.sessions import USER_SESSION_COOKIE, create_user_session


def _engines(tmp_path):
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    return state_engine, index_engine


async def _columns(conn, table: str) -> dict:
    return await conn.run_sync(
        lambda sync_conn: {col["name"]: col for col in inspect(sync_conn).get_columns(table)}
    )


async def test_v15_to_v16_adds_popular_strategy_home_order_featured(tmp_path, monkeypatch):
    """Fresh init reaches v16 with the three new columns present."""
    state_engine, index_engine = _engines(tmp_path)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    async with state_engine.connect() as conn:
        assert await get_state_schema_version(conn) == CURRENT_SCHEMA_VERSION
        settings_cols = await _columns(conn, "site_settings")
        assert "popular_strategy" in settings_cols
        assert str(settings_cols["popular_strategy"]["default"]).strip("'\"") == "recent"
        root_cols = await _columns(conn, "content_root_mappings")
        assert "home_order" in root_cols
        entry_cols = await _columns(conn, "catalog_entries")
        assert "featured" in entry_cols

    await state_engine.dispose()
    await index_engine.dispose()


async def test_v15_to_v16_idempotent(tmp_path, monkeypatch):
    """Re-running init keeps v16 stable without duplicating columns/indexes."""
    state_engine, index_engine = _engines(tmp_path)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()
    await database.init_databases()

    async with state_engine.connect() as conn:
        assert await get_state_schema_version(conn) == CURRENT_SCHEMA_VERSION
        entry_cols = await _columns(conn, "catalog_entries")
        assert "featured" in entry_cols

    await state_engine.dispose()
    await index_engine.dispose()


async def test_old_v15_db_upgrades_to_v16(tmp_path, monkeypatch):
    """A v15 state.db (with schema_version=15) upgrades to v16."""
    state_engine, index_engine = _engines(tmp_path)
    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
        await conn.execute(
            text(
                "INSERT OR REPLACE INTO system_settings(key, value, value_type, updated_at) "
                "VALUES('schema_version', '15', 'integer', CURRENT_TIMESTAMP)"
            )
        )
    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)

    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    async with state_engine.connect() as conn:
        assert await get_state_schema_version(conn) == CURRENT_SCHEMA_VERSION
        settings_cols = await _columns(conn, "site_settings")
        assert "popular_strategy" in settings_cols

    await state_engine.dispose()
    await index_engine.dispose()


async def _setup_home_store(monkeypatch, *, popular_strategy: str = "recent"):
    state_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    index_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    index_factory = async_sessionmaker(index_engine, expire_on_commit=False)
    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)
    monkeypatch.setattr(main, "StateSession", state_factory)
    monkeypatch.setattr(auth, "StateSession", state_factory)
    monkeypatch.setattr(main, "IndexSession", index_factory)

    async with state_factory() as state:
        state.add(SiteSettings(id=1, popular_strategy=popular_strategy))
        state.add(ContentRootMapping(id=1, content_type="software", display_name="软件", alist_path="/software", enabled=True, home_order=0))
        state.add(SystemSetting(key="setup_completed", value="true", value_type="string"))
        user = User(username="user", username_normalized="user", password_hash="x", status="active", created_at=utcnow(), updated_at=utcnow())
        state.add(user)
        await state.flush()
        _, user_token = await create_user_session(state, user.id, utcnow())
        await state.commit()
    async with index_factory() as index:
        index.add(Resource(id="r_small_new", name="small-new.zip", path="/software/small-new.zip", parent_id=None, content_type="software", root_mapping_id=1, extension="zip", mime_type="application/zip", size=100, status="active"))
        index.add(Resource(id="r_big_old", name="big-old.iso", path="/software/big-old.iso", parent_id=None, content_type="software", root_mapping_id=1, extension="iso", mime_type="application/x-iso", size=999999, status="active"))
        index.add(Resource(id="r_missing", name="missing.zip", path="/software/missing.zip", parent_id=None, content_type="software", root_mapping_id=1, extension="zip", mime_type="application/zip", size=5, status="missing"))
        await index.commit()
    return state_engine, index_engine, user_token


def _client(user_token: str = ""):
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://testserver")
    if user_token:
        client.cookies.set(USER_SESSION_COOKIE, user_token)
    return client


async def test_home_returns_type_entries_and_popular_strategy(monkeypatch):
    """/api/home includes type_entries and popular_strategy fields."""
    state_engine, index_engine, user_token = await _setup_home_store(monkeypatch)
    try:
        async with _client(user_token) as client:
            resp = await client.get("/api/home")
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["popular_strategy"] == "recent"
            type_entries = body["type_entries"]
            assert len(type_entries) == 5
            types = {e["type"] for e in type_entries}
            assert types == {"software", "image", "video", "document", "file"}
            for entry in type_entries:
                assert entry["url"].startswith("/browse?type=")
                assert "display_name" in entry
                assert "count" in entry
    finally:
        await state_engine.dispose()
        await index_engine.dispose()


async def test_home_popular_not_sorted_by_size(monkeypatch):
    """With recent strategy, popular follows modified_at not size: small-new comes first."""
    from datetime import datetime, timezone
    state_engine, index_engine, user_token = await _setup_home_store(monkeypatch)
    try:
        from cloudsite.models import Resource as Res
        async with main.IndexSession() as index:
            now = datetime.now(timezone.utc)
            from sqlalchemy import update
            await index.execute(update(Res).where(Res.id == "r_small_new").values(modified_at=now))
            await index.execute(update(Res).where(Res.id == "r_big_old").values(modified_at=datetime(2020, 1, 1, tzinfo=timezone.utc)))
            await index.commit()
        async with _client(user_token) as client:
            resp = await client.get("/api/home")
            body = resp.json()
            popular = body["popular"]
            assert popular[0]["id"] == "r_small_new"
    finally:
        await state_engine.dispose()
        await index_engine.dispose()


async def test_browse_returns_all_types(monkeypatch):
    """/api/browse without type returns all type entries and paginated resources."""
    state_engine, index_engine, user_token = await _setup_home_store(monkeypatch)
    try:
        async with _client(user_token) as client:
            resp = await client.get("/api/browse")
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["type"] is None
            assert len(body["type_entries"]) == 5
            assert body["total"] == 2
            assert len(body["items"]) == 2
            assert "catalog_entries" in body
            assert "content_roots" in body
    finally:
        await state_engine.dispose()
        await index_engine.dispose()


async def test_browse_with_type_filter(monkeypatch):
    """/api/browse?type=software filters resources and catalog entries."""
    state_engine, index_engine, user_token = await _setup_home_store(monkeypatch)
    try:
        async with _client(user_token) as client:
            resp = await client.get("/api/browse?type=software")
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["type"] == "software"
            assert body["total"] == 2
            for item in body["items"]:
                assert item["content_type"] == "software"
    finally:
        await state_engine.dispose()
        await index_engine.dispose()




async def test_browse_name_sort_is_real(monkeypatch):
    """/api/browse?sort=name changes the resource order instead of being UI-only."""
    state_engine, index_engine, user_token = await _setup_home_store(monkeypatch)
    try:
        async with _client(user_token) as client:
            resp = await client.get("/api/browse?sort=name")
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["sort"] == "name"
            assert body["order"] == "asc"
            assert [item["id"] for item in body["items"]] == [
                "r_big_old",
                "r_small_new",
            ]
    finally:
        await state_engine.dispose()
        await index_engine.dispose()


async def test_browse_rejects_unknown_sort(monkeypatch):
    """Browse sort is allow-listed instead of reaching repository column lookup."""
    state_engine, index_engine, user_token = await _setup_home_store(monkeypatch)
    try:
        async with _client(user_token) as client:
            resp = await client.get("/api/browse?sort=unknown")
            assert resp.status_code == 422
    finally:
        await state_engine.dispose()
        await index_engine.dispose()

async def test_browse_empty_type_returns_zero(monkeypatch):
    """/api/browse?type=image with no images returns empty items."""
    state_engine, index_engine, user_token = await _setup_home_store(monkeypatch)
    try:
        async with _client(user_token) as client:
            resp = await client.get("/api/browse?type=image")
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["total"] == 0
            assert body["items"] == []
    finally:
        await state_engine.dispose()
        await index_engine.dispose()


async def test_browse_preserves_status_filter(monkeypatch):
    """/api/browse keeps the legacy arbitrary status filter semantics."""
    state_engine, index_engine, user_token = await _setup_home_store(monkeypatch)
    try:
        async with _client(user_token) as client:
            resp = await client.get("/api/browse?status=missing")
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["status"] == "missing"
            assert body["total"] == 1
            assert [item["id"] for item in body["items"]] == ["r_missing"]
            assert body["counts"]["software"] == 1
    finally:
        await state_engine.dispose()
        await index_engine.dispose()
