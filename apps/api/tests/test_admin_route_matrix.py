"""M7: 后台路由矩阵安全测试。

从 FastAPI 实例自动盘点所有 /api/admin/** 路由，对每个非公开端点
验证匿名请求被统一边界拦截（403 ADMIN_REQUIRED 或 409 SETUP_REQUIRED），
而非进入业务处理器产生 404/422/500。

对应 SEC-001 开发手册 §6.1 路由矩阵测试。
"""
import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import auth, main
from cloudsite.admin_auth import is_public_admin_endpoint
from cloudsite.database import StateBase
from cloudsite.models import SiteSettings, SystemSetting


async def _matrix_client(monkeypatch):
    """创建已初始化（setup_completed=true）的测试客户端。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    async with factory() as session:
        session.add(SiteSettings(id=1))
        session.add(SystemSetting(key="setup_completed", value="true", value_type="string"))
        await session.commit()
    monkeypatch.setattr(main, "StateSession", factory)
    monkeypatch.setattr(auth, "StateSession", factory)
    transport = httpx.ASGITransport(app=main.app)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    return client, engine


def _collect_admin_endpoints() -> list[tuple[str, str]]:
    """盘点所有 (method, path) 后台端点，动态参数用 999999 实例化。"""
    endpoints: list[tuple[str, str]] = []
    for route in main.app.routes:
        if not hasattr(route, "path") or not route.path.startswith("/api/admin"):
            continue
        methods = getattr(route, "methods", None) or set()
        for method in sorted(methods):
            if method in ("HEAD", "OPTIONS"):
                continue
            path = route.path
            # 实例化动态路径
            path = path.replace("{folder_id}", "999999")
            path = path.replace("{collection_id}", "999999")
            path = path.replace("{share_id}", "999999")
            path = path.replace("{submission_id}", "999999")
            path = path.replace("{notification_id}", "999999")
            path = path.replace("{run_id}", "999999")
            path = path.replace("{user_id}", "999999")
            path = path.replace("{id}", "999999")
            endpoints.append((method, path))
    return sorted(set(endpoints))


async def test_all_non_public_admin_endpoints_reject_anonymous(monkeypatch):
    """每个非公开 admin 端点必须拒绝匿名请求（403/409），不能进入业务处理器。"""
    client, engine = await _matrix_client(monkeypatch)
    endpoints = _collect_admin_endpoints()
    assert len(endpoints) >= 30, f"后台端点数量过少: {len(endpoints)}"

    failures: list[str] = []
    async with client:
        for method, path in endpoints:
            if is_public_admin_endpoint(method, path):
                continue  # 公开端点不测
            try:
                response = await client.request(method, path)
            except Exception as exc:
                failures.append(f"{method} {path} -> 异常: {exc}")
                continue
            # 必须是 403 ADMIN_REQUIRED 或 409 SETUP_REQUIRED
            if response.status_code not in (403, 409):
                failures.append(
                    f"{method} {path} -> {response.status_code}（期望 403/409，认证未在业务前拦截）"
                )
                continue
            detail = response.json().get("detail", {})
            code = detail.get("code", "") if isinstance(detail, dict) else ""
            if code not in ("ADMIN_REQUIRED", "SETUP_REQUIRED"):
                failures.append(f"{method} {path} -> {response.status_code} code={code}")
    await engine.dispose()
    assert not failures, "路由矩阵安全测试失败:\n" + "\n".join(failures)


async def test_setup_required_state_returns_409(monkeypatch):
    """未初始化状态下，非公开 admin 端点返回 409 SETUP_REQUIRED。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    async with factory() as session:
        session.add(SiteSettings(id=1))
        await session.commit()
    monkeypatch.setattr(main, "StateSession", factory)
    monkeypatch.setattr(auth, "StateSession", factory)
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/admin/system")
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "SETUP_REQUIRED"
    await engine.dispose()


async def test_public_endpoints_accessible_without_admin_cookie(monkeypatch):
    """公开端点在未认证时可访问（不返回 403 ADMIN_REQUIRED）。"""
    client, engine = await _matrix_client(monkeypatch)
    async with client:
        status = await client.get("/api/admin/auth/status")
        assert status.status_code == 200
        assert status.json()["mode"] == "login_required"
        setup_status = await client.get("/api/admin/setup/status")
        assert setup_status.status_code == 200
        assert setup_status.json()["setup_required"] is False
    await engine.dispose()


async def test_forged_admin_cookie_rejected(monkeypatch):
    """伪造的管理员 Cookie 被拒绝。"""
    client, engine = await _matrix_client(monkeypatch)
    async with client:
        response = await client.get(
            "/api/admin/system",
            cookies={main.SESSION_COOKIE: "fake.payload.signature"},
        )
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "ADMIN_REQUIRED"
    await engine.dispose()


async def test_valid_admin_cookie_passes(monkeypatch):
    """有效的管理员 Cookie 可以访问后台。"""
    client, engine = await _matrix_client(monkeypatch)
    admin_cookies = {main.SESSION_COOKIE: main.create_session_token("admin")}
    async with client:
        response = await client.get("/api/admin/auth/status", cookies=admin_cookies)
        assert response.status_code == 200
        assert response.json()["mode"] == "authenticated"
    await engine.dispose()
