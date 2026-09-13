"""M3 发布范围统一过滤：旧分享接口与首页缓存回归测试。

覆盖：
1. 旧兼容接口 /api/shares/{token} 对禁用根的目标返回 invalid_target 而非泄漏。
2. folder 分享的 child_folders/child_resources 限定到主对象所在根，跨 root
   同 parent_id 的脏数据不混入。
3. 首页预热缓存后禁用根，invalidate_home_cache 后再次请求不展示禁用资源。
4. admin root-mapping 写操作（update/delete）触发 invalidate_home_cache。
"""
import httpx
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import auth, main
from cloudsite.database import IndexBase, StateBase
from cloudsite.infrastructure.security import create_session_token
from cloudsite.models import (
    ContentRootMapping,
    Folder,
    Resource,
    Share,
    SiteSettings,
    SystemSetting,
    User,
    utcnow,
)
from cloudsite.routers import home as home_router
from cloudsite.sessions import USER_SESSION_COOKIE, create_user_session


SESSION_COOKIE = main.SESSION_COOKIE


async def _store(monkeypatch, *, second_root_enabled: bool = False):
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
        state.add(ContentRootMapping(id=1, content_type="software", display_name="root-a", alist_path="/root-a", enabled=True))
        state.add(ContentRootMapping(id=2, content_type="software", display_name="root-b", alist_path="/root-b", enabled=second_root_enabled))
        user = User(username="user", username_normalized="user", password_hash="x", status="active", created_at=utcnow(), updated_at=utcnow())
        state.add(user)
        await state.flush()
        _, user_token = await create_user_session(state, user.id, utcnow())
        await state.commit()
    return state_engine, index_engine, state_factory, index_factory, user_token


def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://testserver")


async def test_legacy_share_disabled_root_resource_returns_invalid_target(monkeypatch):
    """旧分享接口对禁用根的资源返回 SHARE_TARGET_INVALID 而非泄漏资源。"""
    state_engine, index_engine, state_factory, index_factory, user_token = await _store(monkeypatch, second_root_enabled=False)
    async with index_factory() as index:
        index.add(Resource(id="b_one", name="one.zip", path="/root-b/one.zip", parent_id=None, content_type="software", root_mapping_id=2, extension="zip", mime_type="application/zip", size=100, thumbnail="", status="active"))
        await index.commit()
    async with state_factory() as state:
        state.add(Share(token="share_b", object_type="resource", object_id="b_one", enabled=True, access_mode="direct"))
        await state.commit()
    async with _client() as client:
        resp = await client.get("/api/shares/share_b", cookies={USER_SESSION_COOKIE: user_token})
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"]["code"] == "SHARE_TARGET_INVALID"
    await state_engine.dispose()
    await index_engine.dispose()


async def test_legacy_share_folder_children_scoped_to_folder_root(monkeypatch):
    """folder 分享的 child 只含主对象所在根的资源，跨 root 同 parent 不混入。"""
    state_engine, index_engine, state_factory, index_factory, user_token = await _store(monkeypatch, second_root_enabled=True)
    async with index_factory() as index:
        index.add(Folder(id="f_a", name="folder-a", path="/root-a/folder-a", parent_id=None, content_type="software", root_mapping_id=1, status="active"))
        index.add(Resource(id="a_in", name="in.zip", path="/root-a/folder-a/in.zip", parent_id="f_a", content_type="software", root_mapping_id=1, extension="zip", mime_type="application/zip", size=100, thumbnail="", status="active"))
        index.add(Resource(id="b_dirty", name="dirty.zip", path="/root-b/folder-a/dirty.zip", parent_id="f_a", content_type="software", root_mapping_id=2, extension="zip", mime_type="application/zip", size=100, thumbnail="", status="active"))
        await index.commit()
    async with state_factory() as state:
        state.add(Share(token="share_f", object_type="folder", object_id="f_a", enabled=True, access_mode="code", code_hash="x", code_version=1))
        await state.commit()
    async with _client() as client:
        resp = await client.get("/api/shares/share_f", cookies={USER_SESSION_COOKIE: user_token})
    assert resp.status_code == 200, resp.text
    payload = resp.json()["target"]
    resource_ids = {r["id"] for r in payload["resources"]}
    assert resource_ids == {"a_in"}, resource_ids
    assert "b_dirty" not in resource_ids
    await state_engine.dispose()
    await index_engine.dispose()


async def test_home_cache_excludes_disabled_root_after_invalidation(monkeypatch):
    """预热缓存后禁用根，invalidate_home_cache 后再次请求不展示禁用资源。"""
    state_engine, index_engine, state_factory, index_factory, user_token = await _store(monkeypatch, second_root_enabled=True)
    async with index_factory() as index:
        for rid, path, root in (("a_one", "/root-a/one.zip", 1), ("b_one", "/root-b/one.zip", 2)):
            index.add(Resource(id=rid, name="one.zip", path=path, parent_id=None, content_type="software", root_mapping_id=root, extension="zip", mime_type="application/zip", size=100, thumbnail="", status="active"))
        await index.commit()
    cookies = {USER_SESSION_COOKIE: user_token}

    async with _client() as client:
        first = await client.get("/api/home", cookies=cookies)
        assert first.status_code == 200, first.text
        first_ids = {r["id"] for r in first.json()["recent"]}
        assert {"a_one", "b_one"} <= first_ids, first_ids

        async with state_factory() as state:
            await state.execute(update(ContentRootMapping).where(ContentRootMapping.id == 2).values(enabled=False))
            await state.commit()
        home_router.invalidate_home_cache()

        second = await client.get("/api/home", cookies=cookies)
        assert second.status_code == 200, second.text
        second_ids = {r["id"] for r in second.json()["recent"]}
        assert "b_one" not in second_ids, second_ids
        assert "a_one" in second_ids, second_ids
    await state_engine.dispose()
    await index_engine.dispose()


async def _admin_store(monkeypatch):
    state_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    async with state_factory() as session:
        session.add(SiteSettings(id=1))
        session.add(SystemSetting(key="setup_completed", value="true", value_type="string"))
        session.add(ContentRootMapping(id=1, content_type="software", display_name="root-a", alist_path="/root-a", enabled=True))
        await session.commit()
    monkeypatch.setattr(main, "StateSession", state_factory)
    monkeypatch.setattr(auth, "StateSession", state_factory)
    return state_engine, state_factory


async def test_admin_root_mapping_update_invalidates_home_cache(monkeypatch):
    """admin 修改 root-mapping 后触发 invalidate_home_cache。"""
    from cloudsite.routers.admin import content_roots

    state_engine, _ = await _admin_store(monkeypatch)
    calls = []
    monkeypatch.setattr(content_roots, "invalidate_home_cache", lambda: calls.append(1))

    async def _passthrough(path, connection_id=1):
        return path
    monkeypatch.setattr(content_roots, "validate_root_mapping_path", _passthrough)

    token = create_session_token("admin")
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.put(
            "/api/admin/root-mappings/1",
            cookies={SESSION_COOKIE: token},
            json={"content_type": "software", "display_name": "root-a", "alist_path": "/root-a", "enabled": False, "sort_order": 0},
        )
    assert resp.status_code == 200, resp.text
    assert calls == [1], calls
    await state_engine.dispose()


async def test_admin_root_mapping_delete_invalidates_home_cache(monkeypatch):
    """admin 删除 root-mapping 后触发 invalidate_home_cache。"""
    from cloudsite.routers.admin import content_roots

    state_engine, state_factory = await _admin_store(monkeypatch)
    async with state_factory() as state:
        state.add(ContentRootMapping(id=2, content_type="software", display_name="root-b", alist_path="/root-b", enabled=True))
        await state.commit()
    calls = []
    monkeypatch.setattr(content_roots, "invalidate_home_cache", lambda: calls.append(1))
    token = create_session_token("admin")
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.delete("/api/admin/root-mappings/2", cookies={SESSION_COOKIE: token})
    assert resp.status_code == 200, resp.text
    assert calls == [1], calls
    await state_engine.dispose()
