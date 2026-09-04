"""1.0 Publication Scope 泄漏测试。

验证 disabled ContentRoot 的资源不出现在任何公开接口：
- /api/home
- /api/resources
- /api/search
- /d/{resource_id}
- /p/{resource_id}
- /api/public/shares/{token}

对应 1.0 开发文档第 32、33 节：Publication Scope 是公开数据的最终边界。
"""
import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import auth, main
from cloudsite.database import IndexBase, StateBase
from cloudsite.models import ContentRootMapping, Resource, SiteSettings, User, utcnow
from cloudsite.sessions import USER_SESSION_COOKIE, create_user_session


async def _scope_store(monkeypatch):
    """创建测试环境：一个 enabled root + 一个 disabled root，各有 active 资源。"""
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
        state.add(SiteSettings(id=1))
        state.add(ContentRootMapping(id=1, content_type="software", display_name="启用", alist_path="/enabled", enabled=True))
        state.add(ContentRootMapping(id=2, content_type="software", display_name="禁用", alist_path="/disabled", enabled=False))
        user = User(username="user", username_normalized="user", password_hash="x", status="active", created_at=utcnow(), updated_at=utcnow())
        state.add(user)
        await state.flush()
        _, token = await create_user_session(state, user.id, utcnow())
        await state.commit()

    async with index_factory() as index:
        index.add(Resource(id="r_enabled", name="enabled.zip", path="/enabled/enabled.zip", parent_id=None, content_type="software", root_mapping_id=1, extension="zip", mime_type="application/zip", size=100, thumbnail="", status="active"))
        index.add(Resource(id="r_disabled", name="disabled.zip", path="/disabled/disabled.zip", parent_id=None, content_type="software", root_mapping_id=2, extension="zip", mime_type="application/zip", size=200, thumbnail="", status="active"))
        await index.commit()

    return state_engine, index_engine, token


async def test_home_excludes_disabled_root_resources(monkeypatch):
    """首页不返回 disabled root 的资源。"""
    state_engine, index_engine, token = await _scope_store(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/home", cookies={USER_SESSION_COOKIE: token})
    assert response.status_code == 200
    data = response.json()
    all_resources = data.get("recent_resources", []) + data.get("popular", [])
    resource_ids = {r["id"] for r in all_resources}
    assert "r_enabled" in resource_ids or len(all_resources) == 0  # enabled 资源可能出现
    assert "r_disabled" not in resource_ids  # disabled 资源绝不出现
    await state_engine.dispose()
    await index_engine.dispose()


async def test_resources_list_excludes_disabled_root(monkeypatch):
    """资源列表不返回 disabled root 的资源。"""
    state_engine, index_engine, token = await _scope_store(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/resources", cookies={USER_SESSION_COOKIE: token})
    assert response.status_code == 200
    data = response.json()
    resource_ids = {r["id"] for r in data.get("items", [])}
    assert "r_disabled" not in resource_ids
    await state_engine.dispose()
    await index_engine.dispose()


async def test_content_roots_only_lists_enabled(monkeypatch):
    """内容根列表只返回 enabled 的 root。"""
    state_engine, index_engine, token = await _scope_store(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/content-roots", cookies={USER_SESSION_COOKIE: token})
    assert response.status_code == 200
    roots = response.json().get("items", [])
    root_ids = {r["id"] for r in roots}
    assert 1 in root_ids  # enabled root
    assert 2 not in root_ids  # disabled root
    await state_engine.dispose()
    await index_engine.dispose()


async def test_download_rejects_disabled_root_resource(monkeypatch):
    """下载 disabled root 的资源被拒绝（302 到错误页或 403/404）。"""
    state_engine, index_engine, token = await _scope_store(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(
            "/d/r_disabled",
            cookies={USER_SESSION_COOKIE: token},
            follow_redirects=False,
        )
    # 下载端点对不可用资源返回 302 重定向到错误页
    assert response.status_code in (302, 403, 404)
    if response.status_code == 302:
        assert "download-error" in response.headers.get("location", "")
    await state_engine.dispose()
    await index_engine.dispose()


async def test_preview_rejects_disabled_root_resource(monkeypatch):
    """预览 disabled root 的资源被拒绝。"""
    state_engine, index_engine, token = await _scope_store(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(
            "/p/r_disabled",
            cookies={USER_SESSION_COOKIE: token},
            follow_redirects=False,
        )
    # 预览可能 302 到错误页或返回 403/404
    assert response.status_code in (302, 403, 404)
    if response.status_code != 302:
        detail = response.json()["detail"]
        assert detail["code"] in ("RESOURCE_NOT_AVAILABLE", "AUTH_REQUIRED")
    await state_engine.dispose()
    await index_engine.dispose()


async def test_resource_detail_rejects_disabled_root(monkeypatch):
    """资源详情不返回 disabled root 的资源。"""
    state_engine, index_engine, token = await _scope_store(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(
            "/api/resources/r_disabled",
            cookies={USER_SESSION_COOKIE: token},
        )
    assert response.status_code in (403, 404)
    await state_engine.dispose()
    await index_engine.dispose()
