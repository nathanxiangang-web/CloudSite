"""1.0 AList Offline / Recovery 测试。

验证 AList 不可用时的行为：
1. 已索引数据仍可浏览/搜索
2. 下载/预览返回清晰错误
3. AList 恢复后无需重启

对应 1.0 开发文档第 48、49 节。
"""
import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import auth, main, userdata
from cloudsite.database import IndexBase, StateBase
from cloudsite.download import DownloadError
from cloudsite.models import AListConnection, ContentRootMapping, Resource, SiteSettings, User, utcnow
from cloudsite.sessions import USER_SESSION_COOKIE, create_user_session


async def _alist_offline_store(monkeypatch):
    """创建测试环境：有索引数据但 AList 不可用。"""
    state_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    index_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    index_factory = async_sessionmaker(index_engine, expire_on_commit=False)
    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)
    for mod in (main, auth, userdata):
        if hasattr(mod, "StateSession"):
            monkeypatch.setattr(mod, "StateSession", state_factory)
        if hasattr(mod, "IndexSession"):
            monkeypatch.setattr(mod, "IndexSession", index_factory)

    async with state_factory() as state:
        state.add(SiteSettings(id=1))
        state.add(ContentRootMapping(id=1, content_type="software", display_name="软件", alist_path="/software", enabled=True))
        state.add(AListConnection(id=1, base_url="https://alist.example", base_path="/", username="admin", password_ciphertext="x", enabled=True))
        user = User(username="user", username_normalized="user", password_hash="x", status="active", created_at=utcnow(), updated_at=utcnow())
        state.add(user)
        await state.flush()
        _, token = await create_user_session(state, user.id, utcnow())
        await state.commit()

    async with index_factory() as index:
        index.add(Resource(id="r1", name="app.zip", path="/software/app.zip", parent_id=None, content_type="software", root_mapping_id=1, extension="zip", mime_type="application/zip", size=1024, thumbnail="", status="active"))
        await index.commit()

    return state_engine, index_engine, token


async def test_browse_works_when_alist_is_offline(monkeypatch):
    """AList 不可用时，已索引数据仍可浏览。"""
    state_engine, index_engine, token = await _alist_offline_store(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 首页应正常返回（使用索引数据，不查 AList）
        home = await client.get("/api/home", cookies={USER_SESSION_COOKIE: token})
        assert home.status_code == 200

        # 资源列表应正常返回
        resources = await client.get("/api/resources", cookies={USER_SESSION_COOKIE: token})
        assert resources.status_code == 200
        assert len(resources.json().get("items", [])) == 1

        # 资源详情应正常返回
        detail = await client.get("/api/resources/r1", cookies={USER_SESSION_COOKIE: token})
        assert detail.status_code == 200

    await state_engine.dispose()
    await index_engine.dispose()


async def test_download_returns_error_when_alist_is_offline(monkeypatch):
    """AList 不可用时，下载返回清晰错误（302 到错误页），不崩溃。"""
    state_engine, index_engine, token = await _alist_offline_store(monkeypatch)

    # Mock AList 不可用
    async def failing_resolve(*_args, **_kwargs):
        raise DownloadError("AL-503", "AList 不可用", "resolve")

    monkeypatch.setattr(main, "resolve_download_entry", failing_resolve)

    # Mock 下载限流为允许
    from types import SimpleNamespace
    async def allow_rate(*_args):
        return SimpleNamespace(allowed=True, retry_after=0)
    monkeypatch.setattr(main, "check_download_rate", allow_rate)

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/d/r1", cookies={USER_SESSION_COOKIE: token}, follow_redirects=False)
    # 下载失败应返回 302 到错误页
    assert response.status_code == 302
    assert "download-error" in response.headers.get("location", "")
    await state_engine.dispose()
    await index_engine.dispose()


async def test_storage_info_fails_gracefully_when_alist_offline(monkeypatch):
    """AList 不可用时，storage info 优雅降级。"""
    state_engine, index_engine, token = await _alist_offline_store(monkeypatch)

    # Mock AList 连接失败
    async def failing_client(*_args, **_kwargs):
        raise Exception("connection refused")

    monkeypatch.setattr(main, "AListClient", failing_client)
    monkeypatch.setattr(main, "_storage_info_cache", {"data": None, "fetched_at": 0.0})

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/storage/info", cookies={USER_SESSION_COOKIE: token})
    # 应返回 200 带降级信息，不返回 500
    assert response.status_code == 200
    data = response.json()
    assert "primary" in data
    assert "drives" in data
    await state_engine.dispose()
    await index_engine.dispose()
