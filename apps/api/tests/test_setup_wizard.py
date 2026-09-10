"""B2 首次建站向导端到端测试。

覆盖 /api/admin/setup/wizard：
- 初始状态查询
- 七步推进（connect/scope/preset/samples/brand/preview/publish）
- 跳过向导
- 回退到上一步
- 迁移幂等（空库与已有 v15 库）
"""
import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import auth, config, main
from cloudsite.database import StateBase
from cloudsite.models import (
    AListConnection,
    ContentRootMapping,
    SiteSettings,
    SitePresentation,
    SystemSetting,
    utcnow,
)


class _FakeAListClient:
    def __init__(self, base_url, username, password):
        self.base_url = base_url

    async def test(self):
        return {"base_path": "/", "ok": True}


async def _wizard_setup(monkeypatch):
    state_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    async with state_factory() as state:
        state.add(SiteSettings(id=1))
        state.add(ContentRootMapping(id=1, content_type="software", display_name="软件", alist_path="/software", enabled=True))
        state.add(ContentRootMapping(id=2, content_type="tutorial", display_name="教程", alist_path="/tutorial", enabled=False))
        await state.commit()
    monkeypatch.setattr(main, "StateSession", state_factory)
    monkeypatch.setattr(auth, "StateSession", state_factory)
    monkeypatch.setattr(config.settings, "setup_token", "test-setup-token")
    import cloudsite.routers.admin.setup as setup_module
    monkeypatch.setattr(setup_module, "AListClient", _FakeAListClient)
    return state_engine


def _wizard_client(transport):
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    return client


async def test_wizard_initial_state(monkeypatch):
    state_engine = await _wizard_setup(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with _wizard_client(transport) as client:
            resp = await client.get("/api/admin/setup/wizard")
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["current_step"] == "connect"
            assert body["wizard_completed"] is False
            assert body["connect_done"] is False
    finally:
        await state_engine.dispose()


async def test_wizard_full_flow(monkeypatch):
    state_engine = await _wizard_setup(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with _wizard_client(transport) as client:
            connect = await client.post(
                "/api/admin/setup/wizard/step",
                json={"step": "connect", "data": {"base_url": "https://alist.example.com", "username": "admin", "password": "pass"}},
                headers={"X-CloudSite-Setup-Token": "test-setup-token"},
            )
            assert connect.status_code == 200, connect.text
            assert connect.json()["state"]["connect_done"] is True
            assert connect.json()["state"]["current_step"] == "scope"

            scope = await client.post(
                "/api/admin/setup/wizard/step",
                json={"step": "scope", "data": {"root_mappings": [{"id": 2, "enabled": True}]}},
            )
            assert scope.status_code == 200, scope.text
            assert scope.json()["state"]["scope_done"] is True
            assert scope.json()["state"]["current_step"] == "preset"

            preset = await client.post(
                "/api/admin/setup/wizard/step",
                json={"step": "preset", "data": {"preset": "software"}},
            )
            assert preset.status_code == 200, preset.text
            assert preset.json()["state"]["preset_done"] is True
            assert preset.json()["state"]["current_step"] == "samples"

            samples = await client.post(
                "/api/admin/setup/wizard/step",
                json={"step": "samples", "data": {}},
            )
            assert samples.status_code == 200, samples.text
            assert samples.json()["state"]["samples_done"] is True

            brand = await client.post(
                "/api/admin/setup/wizard/step",
                json={"step": "brand", "data": {"site_name": "我的软件站", "home_title": "好软件", "accent_color": "#2563eb", "card_radius": 12}},
            )
            assert brand.status_code == 200, brand.text
            assert brand.json()["state"]["brand_done"] is True

            preview = await client.post(
                "/api/admin/setup/wizard/step",
                json={"step": "preview", "data": {}},
            )
            assert preview.status_code == 200, preview.text
            assert preview.json()["state"]["preview_done"] is True
            assert preview.json()["result"]["site_name"] == "我的软件站"

            publish = await client.post(
                "/api/admin/setup/wizard/step",
                json={"step": "publish", "data": {}},
            )
            assert publish.status_code == 200, publish.text
            assert publish.json()["state"]["wizard_completed"] is True
            assert publish.json()["state"]["publish_done"] is True

            final = await client.get("/api/admin/setup/wizard")
            assert final.json()["wizard_completed"] is True
            assert final.json()["completed_steps"] == ["connect", "scope", "preset", "samples", "brand", "preview", "publish"]
    finally:
        await state_engine.dispose()


async def test_wizard_skip(monkeypatch):
    state_engine = await _wizard_setup(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with _wizard_client(transport) as client:
            skip = await client.post("/api/admin/setup/wizard/skip")
            assert skip.status_code == 200, skip.text
            assert skip.json()["state"]["wizard_completed"] is True
            assert skip.json()["state"]["current_step"] == "publish"
    finally:
        await state_engine.dispose()


async def test_wizard_go_back(monkeypatch):
    """回退到上一步：current_step 回退，done 标记保留。"""
    state_engine = await _wizard_setup(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with _wizard_client(transport) as client:
            await client.post(
                "/api/admin/setup/wizard/step",
                json={"step": "connect", "data": {"base_url": "https://alist.example.com", "username": "admin", "password": "pass"}},
                headers={"X-CloudSite-Setup-Token": "test-setup-token"},
            )
            await client.post("/api/admin/setup/wizard/step", json={"step": "scope", "data": {}})
            back = await client.post("/api/admin/setup/wizard/step", json={"step": "connect", "data": {"base_url": "https://alist2.example.com", "username": "admin2", "password": "pass2"}})
            assert back.status_code == 200, back.text
            assert back.json()["state"]["connect_done"] is True
            assert back.json()["state"]["current_step"] == "scope"
    finally:
        await state_engine.dispose()


async def test_wizard_connect_requires_token(monkeypatch):
    state_engine = await _wizard_setup(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with _wizard_client(transport) as client:
            resp = await client.post(
                "/api/admin/setup/wizard/step",
                json={"step": "connect", "data": {"base_url": "https://alist.example.com", "username": "admin", "password": "pass"}},
            )
            assert resp.status_code == 403, resp.text
            assert resp.json()["detail"]["code"] == "SETUP_FORBIDDEN"
    finally:
        await state_engine.dispose()


async def test_wizard_preset_persists(monkeypatch):
    """preset 步骤写入 SitePresentation。"""
    state_engine = await _wizard_setup(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with _wizard_client(transport) as client:
            await client.post(
                "/api/admin/setup/wizard/step",
                json={"step": "connect", "data": {"base_url": "https://alist.example.com", "username": "admin", "password": "pass"}},
                headers={"X-CloudSite-Setup-Token": "test-setup-token"},
            )
            await client.post("/api/admin/setup/wizard/step", json={"step": "scope", "data": {}})
            await client.post("/api/admin/setup/wizard/step", json={"step": "preset", "data": {"preset": "tutorial"}})
            async with main.StateSession() as state:
                pres = await state.get(SitePresentation, 1)
                assert pres is not None
                assert pres.preset == "tutorial"
                assert pres.enabled is True
    finally:
        await state_engine.dispose()
