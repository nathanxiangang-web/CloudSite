"""B2 公开发布范围端到端测试。

覆盖：
- CatalogEntry.publicly_visible 字段默认 False
- GET /sitemap.xml 只含 publicly_visible=True 条目
- PUT /api/admin/catalog/entries/{id}/publication-scope 切换公开
- GET /api/public/catalog/{id} 公开 DTO（不含管理敏感信息）
- 撤回公开清除缓存
- 迁移幂等：v15→v16 在空库与已有 v15 库均可运行
"""
import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import auth, main
from cloudsite.database import StateBase
from cloudsite.models import CatalogEntry, SiteSettings, SystemSetting, utcnow
from cloudsite.services.publication_scope import (
    build_sitemap_xml,
    invalidate_sitemap_cache,
    is_publicly_visible,
    public_entry_dto,
)


async def _pub_setup(monkeypatch, *, with_entries=True):
    state_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    index_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as conn:
        from cloudsite.database import IndexBase
        await conn.run_sync(IndexBase.metadata.create_all)
    state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    index_factory = async_sessionmaker(index_engine, expire_on_commit=False)
    async with state_factory() as state:
        state.add(SiteSettings(id=1))
        state.add(SystemSetting(key="setup_completed", value="true", value_type="string"))
        if with_entries:
            state.add(CatalogEntry(
                entry_id="ce_" + "a" * 32, content_type="software", slug="ubuntu",
                title="Ubuntu 22.04", summary="LTS", status="published",
                publicly_visible=True, published_at=utcnow(),
            ))
            state.add(CatalogEntry(
                entry_id="ce_" + "b" * 32, content_type="software", slug="debian",
                title="Debian 12", summary="稳定", status="published",
                publicly_visible=False, published_at=utcnow(),
            ))
            state.add(CatalogEntry(
                entry_id="ce_" + "c" * 32, content_type="tutorial", slug="guide",
                title="入门指南", summary="", status="draft",
                publicly_visible=True,
            ))
        await state.commit()
    monkeypatch.setattr(main, "StateSession", state_factory)
    monkeypatch.setattr(auth, "StateSession", state_factory)
    monkeypatch.setattr(main, "IndexSession", index_factory)
    return state_engine, index_engine


def _admin_client(transport):
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    client.cookies.set(main.SESSION_COOKIE, main.create_session_token("admin"))
    return client


async def test_publicly_visible_defaults_false(monkeypatch):
    """新建 CatalogEntry 默认 publicly_visible=False。"""
    state_engine, index_engine = await _pub_setup(monkeypatch, with_entries=False)
    try:
        async with main.StateSession() as state:
            entry = CatalogEntry(entry_id="ce_" + "d" * 32, content_type="software", slug="test", title="Test", status="draft")
            state.add(entry)
            await state.commit()
            assert entry.publicly_visible is False
    finally:
        await state_engine.dispose()
        await index_engine.dispose()


async def test_sitemap_only_contains_public_entries(monkeypatch):
    state_engine, index_engine = await _pub_setup(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.get("/sitemap.xml")
        assert resp.status_code == 200, resp.text
        assert "application/xml" in resp.headers.get("content-type", "")
        body = resp.text
        assert "ce_" + "a" * 32 in body
        assert "ce_" + "b" * 32 not in body
        assert "ce_" + "c" * 32 not in body
    finally:
        await state_engine.dispose()
        await index_engine.dispose()


async def test_admin_toggle_publication_scope(monkeypatch):
    state_engine, index_engine = await _pub_setup(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with _admin_client(transport) as admin:
            withdraw = await admin.put(
                f"/api/admin/catalog/entries/ce_{'a' * 32}/publication-scope",
                json={"publicly_visible": False},
            )
            assert withdraw.status_code == 200, withdraw.text
            assert withdraw.json()["publicly_visible"] is False

            resp = await admin.get("/sitemap.xml")
            assert "ce_" + "a" * 32 not in resp.text

            publish = await admin.put(
                f"/api/admin/catalog/entries/ce_{'b' * 32}/publication-scope",
                json={"publicly_visible": True},
            )
            assert publish.status_code == 200, publish.text
            resp2 = await admin.get("/sitemap.xml")
            assert "ce_" + "b" * 32 in resp2.text
    finally:
        await state_engine.dispose()
        await index_engine.dispose()


async def test_public_catalog_dto_excludes_admin_fields(monkeypatch):
    """公开 DTO 不含管理敏感信息（revision、sort_order、cover_resource_id）。"""
    state_engine, index_engine = await _pub_setup(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.get(f"/api/public/catalog/ce_{'a' * 32}")
            assert resp.status_code == 200, resp.text
            dto = resp.json()
            assert dto["entry_id"] == "ce_" + "a" * 32
            assert dto["title"] == "Ubuntu 22.04"
            assert dto["publicly_visible"] is True
            assert "revision" not in dto
            assert "sort_order" not in dto
            assert "cover_resource_id" not in dto
            assert "status" not in dto

            not_public = await client.get(f"/api/public/catalog/ce_{'b' * 32}")
            assert not_public.status_code == 404, not_public.text
    finally:
        await state_engine.dispose()
        await index_engine.dispose()


async def test_publication_scope_list(monkeypatch):
    state_engine, index_engine = await _pub_setup(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with _admin_client(transport) as admin:
            resp = await admin.get("/api/admin/publication-scope")
            assert resp.status_code == 200, resp.text
            items = resp.json()["items"]
            assert len(items) == 3
            by_id = {i["entry_id"]: i for i in items}
            assert by_id["ce_" + "a" * 32]["publicly_visible"] is True
            assert by_id["ce_" + "b" * 32]["publicly_visible"] is False
    finally:
        await state_engine.dispose()
        await index_engine.dispose()


async def test_is_publicly_visible_helper():
    """辅助函数：仅 published + publicly_visible 才公开可见。"""
    e1 = CatalogEntry(entry_id="ce_x", content_type="software", slug="x", title="X", status="published", publicly_visible=True)
    e2 = CatalogEntry(entry_id="ce_y", content_type="software", slug="y", title="Y", status="published", publicly_visible=False)
    e3 = CatalogEntry(entry_id="ce_z", content_type="software", slug="z", title="Z", status="draft", publicly_visible=True)
    assert is_publicly_visible(e1) is True
    assert is_publicly_visible(e2) is False
    assert is_publicly_visible(e3) is False


async def test_build_sitemap_xml_format():
    entries = [
        CatalogEntry(entry_id="ce_a", content_type="software", slug="a", title="A", status="published", publicly_visible=True),
        CatalogEntry(entry_id="ce_b", content_type="software", slug="b", title="B", status="published", publicly_visible=False),
    ]
    xml = build_sitemap_xml(entries, "https://example.com")
    assert "<?xml" in xml
    assert "<urlset" in xml
    assert "https://example.com/catalog/ce_a" in xml
    assert "ce_b" not in xml


async def test_migration_v15_to_v16_idempotent(tmp_path, monkeypatch):
    """迁移幂等：空库和已有 v15 库都能运行到 v16。"""
    from cloudsite import database
    from cloudsite.migrations import CURRENT_SCHEMA_VERSION, get_state_schema_version

    assert CURRENT_SCHEMA_VERSION == 24
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()
    await database.init_databases()
    async with state_engine.connect() as conn:
        assert await get_state_schema_version(conn) == 24
    await state_engine.dispose()
    await index_engine.dispose()


async def test_migration_v15_to_v16_old_db(tmp_path, monkeypatch):
    """已有 v15 数据库升级到 v16，setup_wizard_state 表创建、publicly_visible 列添加。"""
    from cloudsite import database
    from cloudsite.migrations import STATE_MIGRATIONS, get_state_schema_version, set_state_schema_version

    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
        await set_state_schema_version(conn, 15)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()
    async with state_engine.connect() as conn:
        assert await get_state_schema_version(conn) == 24
        from sqlalchemy import text
        tables = (await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))).all()
        assert "setup_wizard_state" in {r[0] for r in tables}
        cols = (await conn.execute(text("PRAGMA table_info(catalog_entries)"))).all()
        assert "publicly_visible" in {r[1] for r in cols}
    await state_engine.dispose()
    await index_engine.dispose()
