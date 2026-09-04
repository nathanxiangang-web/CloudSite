"""1.0 错误契约回归测试。

验证所有错误响应：
1. 统一格式 {"detail": {"code": "...", "message": "..."}}
2. 不泄漏 traceback / internal path / secret
3. 覆盖 404 / 422 / 500 / 401 / 403 等状态码
"""
import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import auth, main
from cloudsite.database import StateBase
from cloudsite.models import AListConnection


async def _setup_client(monkeypatch):
    """创建使用内存数据库的测试客户端。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)
    monkeypatch.setattr(main, "StateSession", factory)
    monkeypatch.setattr(auth, "StateSession", factory)
    transport = httpx.ASGITransport(app=main.app)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    return client, factory, engine


async def test_http_404_uses_structured_detail():
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/not-a-route")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "HTTP_404"
    assert isinstance(response.json()["detail"]["message"], str)


async def test_validation_errors_use_stable_code_without_internal_details():
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/api/auth/login", json={})
    assert response.status_code == 422
    assert response.json() == {
        "detail": {"code": "VALIDATION_ERROR", "message": "请求参数格式不正确"}
    }


async def test_health_is_public_and_returns_version():
    """健康检查是公开端点，只暴露 status + version，不泄漏内部信息。"""
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert "version" in body
    assert "secret" not in body
    assert "password" not in body
    assert "token" not in body
    assert "key" not in body


async def test_admin_protected_route_returns_admin_required(monkeypatch):
    """未认证访问 admin 路由返回 ADMIN_REQUIRED。"""
    client, factory, engine = await _setup_client(monkeypatch)
    # 需要一个 enabled AListConnection 才会触发 admin 认证检查
    async with factory() as session:
        session.add(AListConnection(
            id=1, base_url="https://alist.example", username="admin",
            password_ciphertext="x", enabled=True,
        ))
        await session.commit()
    async with client:
        response = await client.get("/api/admin/system")
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["code"] == "ADMIN_REQUIRED"
    assert isinstance(detail["message"], str)
    await engine.dispose()


async def test_user_protected_route_returns_auth_required(monkeypatch):
    """未认证访问用户路由返回 AUTH_REQUIRED。"""
    client, _, engine = await _setup_client(monkeypatch)
    async with client:
        response = await client.get("/api/home")
    assert response.status_code == 401
    detail = response.json()["detail"]
    assert detail["code"] == "AUTH_REQUIRED"
    assert isinstance(detail["message"], str)
    await engine.dispose()


async def test_error_responses_never_leak_traceback_or_internal_path(monkeypatch):
    """错误响应不应包含 traceback、文件路径或 Python 内部信息。"""
    client, factory, engine = await _setup_client(monkeypatch)
    async with factory() as session:
        session.add(AListConnection(
            id=1, base_url="https://alist.example", username="admin",
            password_ciphertext="x", enabled=True,
        ))
        await session.commit()
    async with client:
        responses = [
            await client.get("/not-a-route"),
            await client.post("/api/auth/login", json={}),
            await client.get("/api/admin/system"),
            await client.get("/api/home"),
        ]
    for response in responses:
        text = response.text
        assert "Traceback" not in text
        assert "File \"" not in text
        assert "cloudsite/" not in text
        assert "site-packages" not in text
        assert "secret_key" not in text.lower()
        assert "CLOUDSITE_SECRET" not in text
    await engine.dispose()


async def test_share_not_found_uses_stable_code(monkeypatch):
    """不存在的分享返回 SHARE_NOT_FOUND，不是通用 404。"""
    client, _, engine = await _setup_client(monkeypatch)
    async with client:
        response = await client.get("/api/public/shares/not-a-share")
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["code"] == "SHARE_NOT_FOUND"
    await engine.dispose()


async def test_all_error_responses_have_code_and_message(monkeypatch):
    """所有错误响应的 detail 必须包含 code 和 message 字段。"""
    client, factory, engine = await _setup_client(monkeypatch)
    async with factory() as session:
        session.add(AListConnection(
            id=1, base_url="https://alist.example", username="admin",
            password_ciphertext="x", enabled=True,
        ))
        await session.commit()
    async with client:
        error_responses = [
            await client.get("/not-a-route"),
            await client.post("/api/auth/login", json={}),
            await client.get("/api/admin/system"),
            await client.get("/api/home"),
            await client.get("/d/not-a-resource"),
            await client.get("/p/not-a-resource"),
            await client.get("/api/public/shares/not-a-share"),
        ]
    for response in error_responses:
        assert response.status_code >= 400
        body = response.json()
        assert "detail" in body
        assert "code" in body["detail"]
        assert "message" in body["detail"]
        assert isinstance(body["detail"]["code"], str)
        assert isinstance(body["detail"]["message"], str)
        assert len(body["detail"]["code"]) > 0
    await engine.dispose()
