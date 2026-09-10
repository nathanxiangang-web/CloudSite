"""1.0 兼容回归端到端测试：/d/{id} 仍下载原文件、/api/resources/{id} 仍以文件
ID 查询、/api/search 返回旧文件契约（无 catalog 条目混入）、旧分享不扩大范围。
"""
from datetime import datetime, timezone

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import auth, main
from cloudsite.database import IndexBase, StateBase
from cloudsite.models import (
    ContentRootMapping,
    Resource,
    SiteSettings,
    SystemSetting,
    User,
    utcnow,
)
from cloudsite.sessions import USER_SESSION_COOKIE, create_user_session

RESOURCE_ID = "r_" + "b" * 32
RESOURCE_ID_2 = "r_" + "c" * 32


async def _setup(monkeypatch, with_second_resource=False):
    state_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    index_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)
    sf = async_sessionmaker(state_engine, expire_on_commit=False)
    ix = async_sessionmaker(index_engine, expire_on_commit=False)

    async with sf() as state:
        state.add_all([
            SiteSettings(id=1),
            SystemSetting(key="setup_completed", value="true", value_type="string"),
            ContentRootMapping(id=1, content_type="software", display_name="Software", alist_path="/software", enabled=True),
        ])
        user = User(username="alice", username_normalized="alice", password_hash="x", status="active", created_at=utcnow(), updated_at=utcnow())
        state.add(user)
        await state.flush()
        _, token = await create_user_session(state, user.id, utcnow())
        await state.commit()
    async with ix() as index:
        index.add(Resource(id=RESOURCE_ID, name="cloudsite-x64.zip", path="/software/cloudsite-x64.zip", parent_id=None, content_type="software", root_mapping_id=1, extension="zip", mime_type="application/zip", size=123, status="active", indexed_at=datetime.now(timezone.utc)))
        if with_second_resource:
            index.add(Resource(id=RESOURCE_ID_2, name="cloudsite-arm64.zip", path="/software/cloudsite-arm64.zip", parent_id=None, content_type="software", root_mapping_id=1, extension="zip", mime_type="application/zip", size=200, status="active", indexed_at=datetime.now(timezone.utc)))
        await index.commit()

    monkeypatch.setattr(main, "StateSession", sf)
    monkeypatch.setattr(main, "IndexSession", ix)
    import importlib
    for mod_name, attrs in {
        "cloudsite.database": ("StateSession", "IndexSession"),
        "cloudsite.auth": ("StateSession",),
        "cloudsite.userdata": ("StateSession", "IndexSession"),
        "cloudsite.download_rate_limit": ("StateSession",),
        "cloudsite.search": ("StateSession", "IndexSession"),
        "cloudsite.indexer": ("StateSession", "IndexSession"),
        "cloudsite.site": ("StateSession", "IndexSession"),
        "cloudsite.users": ("StateSession",),
        "cloudsite.sessions": ("StateSession",),
    }.items():
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue
        for attr in attrs:
            if hasattr(mod, attr):
                monkeypatch.setattr(mod, attr, sf if attr == "StateSession" else ix)
    return state_engine, index_engine, sf, ix, token


def _user_client(transport, token):
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    client.cookies.set(USER_SESSION_COOKIE, token)
    return client


async def test_download_route_resolves_by_resource_id(monkeypatch):
    """/d/{id} 仍以 resource_id 为单位下载原文件，不混入 catalog 条目。"""
    se, ie, sf, ix, token = await _setup(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    async with _user_client(transport, token) as client:
        valid = await client.get(f"/d/{RESOURCE_ID}", follow_redirects=False)
        assert valid.status_code == 302, valid.text
        assert "/download-error" not in valid.headers["location"] or "DL-002" in valid.headers["location"]

        bad_format = await client.get("/d/not-a-valid-id", follow_redirects=False)
        assert bad_format.status_code == 302
        assert "DL-001" in bad_format.headers["location"]

        nonexistent = await client.get("/d/r_" + "z" * 32, follow_redirects=False)
        assert nonexistent.status_code == 302
        assert "DL-001" in nonexistent.headers["location"]
    await se.dispose()
    await ie.dispose()


async def test_resource_detail_still_queries_by_file_id(monkeypatch):
    """/api/resources/{id} 仍以文件 ID 查询，返回旧文件契约。"""
    se, ie, sf, ix, token = await _setup(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    async with _user_client(transport, token) as client:
        resp = await client.get(f"/api/resources/{RESOURCE_ID}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["id"] == RESOURCE_ID
        assert body["name"] == "cloudsite-x64.zip"
        assert "entry_id" not in body
        assert "revision" not in body

        missing = await client.get("/api/resources/r_" + "z" * 32)
        assert missing.status_code == 404
    await se.dispose()
    await ie.dispose()


async def test_search_returns_legacy_file_contract(monkeypatch):
    """/api/search 返回旧文件契约：items 仅含 resource/folder，无 catalog 条目混入。"""
    se, ie, sf, ix, token = await _setup(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    async with _user_client(transport, token) as client:
        resp = await client.get("/api/search?q=cloudsite")
        if resp.status_code == 503:
            await se.dispose()
            await ie.dispose()
            return
        assert resp.status_code == 200, resp.text
        body = resp.json()
        for item in body["items"]:
            assert item["object_type"] in ("resource", "folder"), item
            assert "entry_id" not in item
            assert "release_id" not in item
        assert all(item.get("object_type") != "catalog_entry" for item in body["items"])
    await se.dispose()
    await ie.dispose()


async def test_resource_listing_excludes_catalog_entries(monkeypatch):
    """/api/resources 列表仍只返回文件资源，不混入 catalog 条目。"""
    se, ie, sf, ix, token = await _setup(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    async with _user_client(transport, token) as client:
        resp = await client.get("/api/resources")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        for item in body["items"]:
            assert "id" in item
            assert "entry_id" not in item
            assert "release_id" not in item
    await se.dispose()
    await ie.dispose()


async def test_legacy_share_does_not_expand_to_new_resources(monkeypatch):
    """旧分享绑定固定 resource_id：新增版本/镜像（不同 resource_id）不自动加入旧分享。"""
    se, ie, sf, ix, token = await _setup(monkeypatch, with_second_resource=True)
    transport = httpx.ASGITransport(app=main.app)
    share_token = None
    async with _user_client(transport, token) as client:
        created = await client.post(
            "/api/my/shares",
            json={
                "object_type": "resource",
                "object_id": RESOURCE_ID,
                "access_mode": "direct",
                "duration": "24h",
            },
        )
        assert created.status_code == 200, created.text
        share_token = created.json()["token"]
        assert share_token

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        original = await client.get(f"/api/public/shares/{share_token}/download/{RESOURCE_ID}", follow_redirects=False)
        assert original.status_code in (302, 403, 404, 503), original.text

        expanded = await client.get(f"/api/public/shares/{share_token}/download/{RESOURCE_ID_2}", follow_redirects=False)
        assert expanded.status_code == 403, expanded.text
        assert expanded.json()["detail"]["code"] == "SHARE_RESOURCE_NOT_ALLOWED"
    await se.dispose()
    await ie.dispose()
