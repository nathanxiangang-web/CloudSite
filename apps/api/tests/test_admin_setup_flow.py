import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import main
from cloudsite.config import settings
from cloudsite.database import StateBase
from cloudsite.models import AListConnection, SystemSetting
from cloudsite.routers.admin import setup as setup_routes


async def _setup_client(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)

    monkeypatch.setattr(main, "StateSession", factory)
    monkeypatch.setattr(settings, "setup_token", "setup-token-for-integration-test")

    async def fake_alist_test(self):
        return {
            "ok": True,
            "message": "AList connection OK",
            "item_count": 0,
            "base_path": "/",
        }

    monkeypatch.setattr(setup_routes.AListClient, "test", fake_alist_test)

    transport = httpx.ASGITransport(app=main.app)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    return client, factory, engine


async def test_first_install_setup_flow(monkeypatch):
    client, factory, engine = await _setup_client(monkeypatch)

    try:
        async with client:
            status = await client.get("/api/admin/setup/status")
            assert status.status_code == 200
            assert status.json() == {
                "setup_required": True,
                "setup_available": True,
            }

            wrong_token = await client.post(
                "/api/admin/setup/alist",
                headers={"X-CloudSite-Setup-Token": "wrong-token"},
                json={
                    "base_url": "http://alist:5244",
                    "username": "admin",
                    "password": "secret",
                    "remember_credentials": True,
                },
            )
            assert wrong_token.status_code == 403
            assert wrong_token.json()["detail"]["code"] == "SETUP_FORBIDDEN"

            initialized = await client.post(
                "/api/admin/setup/alist",
                headers={"X-CloudSite-Setup-Token": settings.setup_token},
                json={
                    "base_url": "http://alist:5244",
                    "username": "admin",
                    "password": "secret",
                    "remember_credentials": True,
                },
            )
            assert initialized.status_code == 200
            assert initialized.json() == {
                "setup_completed": True,
                "next": "/admin/login",
            }

            after = await client.get("/api/admin/setup/status")
            assert after.status_code == 200
            assert after.json()["setup_required"] is False

        async with factory() as session:
            connection = await session.get(AListConnection, 1)
            assert connection is not None
            assert connection.base_url == "http://alist:5244"
            assert connection.username == "admin"
            assert connection.enabled is True

            setup_completed = await session.scalar(
                select(SystemSetting.value).where(SystemSetting.key == "setup_completed")
            )
            assert setup_completed == "true"
    finally:
        await engine.dispose()


async def test_setup_unavailable_without_token(monkeypatch):
    client, _, engine = await _setup_client(monkeypatch)
    monkeypatch.setattr(settings, "setup_token", "")

    try:
        async with client:
            status = await client.get("/api/admin/setup/status")
            assert status.status_code == 200
            assert status.json() == {
                "setup_required": True,
                "setup_available": False,
            }

            response = await client.post(
                "/api/admin/setup/alist",
                headers={"X-CloudSite-Setup-Token": "anything"},
                json={
                    "base_url": "http://alist:5244",
                    "username": "admin",
                    "password": "secret",
                    "remember_credentials": True,
                },
            )
            assert response.status_code == 503
            assert response.json()["detail"]["code"] == "SETUP_UNAVAILABLE"
    finally:
        await engine.dispose()
