"""B2 首次建站向导端到端测试。

覆盖 /api/admin/setup/wizard：
- 初始状态查询
- 五步真实流程（connect/scope/preset/brand/publish）
- 旧 samples/preview 进度兼容
- 跳过向导
- 回退到上一步
- 预设保存与发布启用语义
"""
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import auth, config, main
from cloudsite.database import StateBase
from cloudsite.models import (
    AListConnection,
    ContentRootMapping,
    SiteSettings,
    SitePresentation,
    SetupWizardState,
    SystemSetting,
    utcnow,
)


class _FakeAListClient:
    def __init__(self, base_url, username, password):
        self.base_url = base_url

    async def test(self):
        return {
            "base_path": "/",
            "ok": True,
            "message": "AList 连接及根目录访问成功",
            "item_count": 2,
        }

    async def list_directories(self, path):
        assert path == "/"
        return [
            {"name": "software", "modified": None},
            {"name": "photos", "modified": None},
        ]

    async def get_path(self, path):
        return {
            "name": path.rsplit("/", 1)[-1],
            "is_dir": True,
        }


async def _wizard_setup(monkeypatch, *, seed_mappings=True):
    state_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    async with state_factory() as state:
        state.add(SiteSettings(id=1))
        if seed_mappings:
            state.add(ContentRootMapping(id=1, content_type="software", display_name="软件", alist_path="/software", enabled=True))
            state.add(ContentRootMapping(id=2, content_type="tutorial", display_name="教程", alist_path="/tutorial", enabled=False))
        await state.commit()
    monkeypatch.setattr(main, "StateSession", state_factory)
    monkeypatch.setattr(auth, "StateSession", state_factory)
    monkeypatch.setattr(config.settings, "setup_token", "test-setup-token")
    from cloudsite.modules.providers.application import connection_admin, root_mappings
    monkeypatch.setattr(
        connection_admin,
        "AListClient",
        _FakeAListClient,
    )
    monkeypatch.setattr(
        root_mappings,
        "AListClient",
        _FakeAListClient,
    )
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


async def test_wizard_legacy_progress_is_normalized(monkeypatch):
    state_engine = await _wizard_setup(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with main.StateSession() as state:
            state.add(
                SetupWizardState(
                    id=1,
                    current_step="samples",
                    completed_steps_json='["connect", "scope", "preset"]',
                    connect_done=True,
                    scope_done=True,
                    preset_done=True,
                    started_at="legacy",
                )
            )
            await state.commit()

        async with _wizard_client(transport) as client:
            samples = await client.get("/api/admin/setup/wizard")
            assert samples.status_code == 200, samples.text
            assert samples.json()["current_step"] == "brand"
            assert samples.json()["samples_done"] is True
            assert samples.json()["completed_steps"] == ["connect", "scope", "preset", "samples"]

            async with main.StateSession() as state:
                row = await state.get(SetupWizardState, 1)
                assert row is not None
                row.current_step = "preview"
                row.brand_done = True
                row.completed_steps_json = '["connect", "scope", "preset", "samples", "brand"]'
                await state.commit()

            preview = await client.get("/api/admin/setup/wizard")
            assert preview.status_code == 200, preview.text
            assert preview.json()["current_step"] == "publish"
            assert preview.json()["preview_done"] is True
            assert preview.json()["completed_steps"] == ["connect", "scope", "preset", "samples", "brand", "preview"]
    finally:
        await state_engine.dispose()


async def test_wizard_fresh_scope_creates_real_root_mappings(monkeypatch):
    state_engine = await _wizard_setup(monkeypatch, seed_mappings=False)
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with _wizard_client(transport) as client:
            connect = await client.post(
                "/api/admin/setup/wizard/step",
                json={
                    "step": "connect",
                    "data": {
                        "base_url": "https://alist.example.com",
                        "username": "admin",
                        "password": "pass",
                        "remember_credentials": False,
                    },
                },
                headers={"X-CloudSite-Setup-Token": "test-setup-token"},
            )
            assert connect.status_code == 200, connect.text
            assert connect.json()["state"]["current_step"] == "scope"

            scope_state = await client.get("/api/admin/setup/wizard")
            assert scope_state.status_code == 200, scope_state.text
            body = scope_state.json()
            assert body["root_mappings"] == []
            assert [item["path"] for item in body["root_directories"]] == [
                "/software",
                "/photos",
            ]
            assert body["scope_error"] == ""

            scope = await client.post(
                "/api/admin/setup/wizard/step",
                json={
                    "step": "scope",
                    "data": {
                        "root_mappings": [
                            {
                                "alist_path": "/software",
                                "display_name": "software",
                                "content_type": "software",
                                "enabled": True,
                                "sort_order": 0,
                            },
                            {
                                "alist_path": "/photos",
                                "display_name": "photos",
                                "content_type": "image",
                                "enabled": True,
                                "sort_order": 1,
                            },
                        ]
                    },
                },
            )
            assert scope.status_code == 200, scope.text
            assert scope.json()["result"]["created"] == 2
            assert scope.json()["state"]["current_step"] == "preset"

            async with main.StateSession() as state:
                rows = list(
                    (
                        await state.scalars(
                            select(ContentRootMapping).order_by(ContentRootMapping.id)
                        )
                    ).all()
                )
                assert [(row.alist_path, row.content_type) for row in rows] == [
                    ("/software", "software"),
                    ("/photos", "image"),
                ]
                connection = await state.get(AListConnection, 1)
                assert connection is not None
                assert connection.password_ciphertext
                assert connection.remember_credentials is True
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
            assert preset.json()["state"]["current_step"] == "brand"
            async with main.StateSession() as state:
                pres = await state.get(SitePresentation, 1)
                assert pres is not None
                assert pres.enabled is False

            brand = await client.post(
                "/api/admin/setup/wizard/step",
                json={"step": "brand", "data": {"site_name": "我的软件站", "home_title": "好软件", "accent_color": "#2563eb", "card_radius": 12}},
            )
            assert brand.status_code == 200, brand.text
            assert brand.json()["state"]["brand_done"] is True
            assert brand.json()["state"]["current_step"] == "publish"

            draft = await client.get("/api/admin/setup/wizard")
            assert draft.status_code == 200, draft.text
            assert draft.json()["draft"]["preset"] == "software"
            assert draft.json()["draft"]["site_name"] == "我的软件站"
            assert draft.json()["draft"]["home_title"] == "好软件"

            publish = await client.post(
                "/api/admin/setup/wizard/step",
                json={"step": "publish", "data": {}},
            )
            assert publish.status_code == 200, publish.text
            assert publish.json()["state"]["wizard_completed"] is True
            assert publish.json()["state"]["publish_done"] is True
            async with main.StateSession() as state:
                pres = await state.get(SitePresentation, 1)
                assert pres is not None
                assert pres.enabled is True

            final = await client.get("/api/admin/setup/wizard")
            assert final.json()["wizard_completed"] is True
            assert final.json()["completed_steps"] == ["connect", "scope", "preset", "brand", "publish"]
    finally:
        await state_engine.dispose()


async def test_wizard_skip(monkeypatch):
    state_engine = await _wizard_setup(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with _wizard_client(transport) as client:
            skip = await client.post(
                "/api/admin/setup/wizard/skip",
                headers={"X-CloudSite-Setup-Token": "test-setup-token"},
            )
            assert skip.status_code == 200, skip.text
            assert skip.json()["state"]["wizard_completed"] is True
            assert skip.json()["state"]["current_step"] == "publish"
    finally:
        await state_engine.dispose()


async def test_wizard_skip_requires_token_before_connect(monkeypatch):
    state_engine = await _wizard_setup(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with _wizard_client(transport) as client:
            skip = await client.post("/api/admin/setup/wizard/skip")
            assert skip.status_code == 403, skip.text
            assert skip.json()["detail"]["code"] == "SETUP_FORBIDDEN"
    finally:
        await state_engine.dispose()


async def test_wizard_go_back(monkeypatch):
    """真实回退只移动 current_step，已完成标记保留。"""
    state_engine = await _wizard_setup(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with _wizard_client(transport) as client:
            await client.post(
                "/api/admin/setup/wizard/step",
                json={"step": "connect", "data": {"base_url": "https://alist.example.com", "username": "admin", "password": "pass"}},
                headers={"X-CloudSite-Setup-Token": "test-setup-token"},
            )
            scope = await client.post(
                "/api/admin/setup/wizard/step",
                json={"step": "scope", "data": {}},
            )
            assert scope.json()["state"]["current_step"] == "preset"

            back = await client.post("/api/admin/setup/wizard/back")
            assert back.status_code == 200, back.text
            assert back.json()["state"]["scope_done"] is True
            assert back.json()["state"]["current_step"] == "scope"
    finally:
        await state_engine.dispose()


async def test_wizard_rejects_out_of_order_publish(monkeypatch):
    state_engine = await _wizard_setup(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with _wizard_client(transport) as client:
            publish = await client.post(
                "/api/admin/setup/wizard/step",
                json={"step": "publish", "data": {}},
            )
            assert publish.status_code == 409, publish.text
            assert publish.json()["detail"]["code"] == "WIZARD_STEP_OUT_OF_ORDER"
            assert publish.json()["detail"]["message"] == "当前应处理步骤：connect"
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
                assert pres.enabled is False
    finally:
        await state_engine.dispose()
