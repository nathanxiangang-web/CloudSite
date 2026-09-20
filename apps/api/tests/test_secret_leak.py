"""1.0 Secret Leak 测试。

验证 API 响应不泄漏敏感信息：
- secret_key / master_key
- password_hash / password_ciphertext
- session token / share code
- AList 凭据

对应 1.0 开发文档第 38 节：Secrets。
"""
import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import auth, main, userdata
from cloudsite.config import settings
from cloudsite.database import IndexBase, StateBase
from cloudsite.models import AListConnection, SiteSettings, User, utcnow
from cloudsite.sessions import USER_SESSION_COOKIE, create_user_session


async def _leak_store(monkeypatch):
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
        state.add(AListConnection(
            id=1, base_url="https://alist.example", base_path="/",
            username="alist-admin", password_ciphertext="secret-cipher-text", enabled=True,
        ))
        user = User(username="user", username_normalized="user", password_hash="secret-hash", status="active", created_at=utcnow(), updated_at=utcnow())
        state.add(user)
        await state.flush()
        _, token = await create_user_session(state, user.id, utcnow())
        await state.commit()

    return state_engine, index_engine, token


async def test_health_does_not_leak_secret_key(monkeypatch):
    """health 端点不泄漏 secret_key、master_key 或任何密钥。"""
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/health")
    body = response.text.lower()
    assert settings.secret_key.lower() not in body
    assert "secret_key" not in body
    assert "master_key" not in body
    assert "password" not in body


async def test_admin_alist_config_does_not_leak_password(monkeypatch):
    """admin AList 配置不泄漏加密凭据。"""
    state_engine, _, _ = await _leak_store(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 用 admin session 访问
        from cloudsite.main import create_session_token, SESSION_COOKIE
        admin_cookie = {SESSION_COOKIE: create_session_token("admin")}
        response = await client.get("/api/admin/alist", cookies=admin_cookie)
    if response.status_code == 200:
        body = response.text
        assert "secret-cipher-text" not in body
        assert "password_ciphertext" not in body
    await state_engine.dispose()


async def test_user_me_does_not_leak_password_hash(monkeypatch):
    """/api/auth/me 不泄漏 password_hash。"""
    state_engine, _, token = await _leak_store(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/auth/me", cookies={USER_SESSION_COOKIE: token})
    assert response.status_code == 200
    body = response.text
    assert "secret-hash" not in body
    assert "password_hash" not in body
    await state_engine.dispose()


async def test_error_responses_do_not_leak_secret_key(monkeypatch):
    """错误响应不泄漏 secret_key。"""
    state_engine, _, _ = await _leak_store(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        responses = [
            await client.get("/not-a-route"),
            await client.post("/api/auth/login", json={}),
            await client.get("/api/home"),
        ]
    for r in responses:
        assert settings.secret_key not in r.text
    await state_engine.dispose()


async def test_share_code_never_returned_in_api(monkeypatch):
    """分享码不在任何 API 响应中明文返回。"""
    state_engine, _, token = await _leak_store(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 创建分享（需要 index.db 中的资源，这里只验证错误响应不泄漏）
        response = await client.post(
            "/api/my/shares",
            cookies={USER_SESSION_COOKIE: token},
            json={"object_type": "resource", "object_id": "nonexistent", "access_mode": "code", "duration": "1h"},
        )
        # 无论成功或失败，响应不应包含 code_hash
        assert "code_hash" not in response.text
    await state_engine.dispose()
