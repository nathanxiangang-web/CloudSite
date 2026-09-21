"""B1 presentation 路由端到端测试。

覆盖 /api/admin/presentation：
- 创建/发布/回退 SitePresentation
- schema 验证拒绝非法 home_blocks
- 预设切换
"""
import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import auth, main
from cloudsite.database import StateBase
from cloudsite.models import SiteSettings, SystemSetting


async def _setup(monkeypatch):
    state_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with state_engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)
    state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    async with state_factory() as state:
        state.add_all(
            [
                SiteSettings(id=1),
                SystemSetting(key="setup_completed", value="true", value_type="string"),
            ]
        )
        await state.commit()
    monkeypatch.setattr(main, "StateSession", state_factory)
    monkeypatch.setattr(auth, "StateSession", state_factory)
    return state_engine


def _admin_client(transport):
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    client.cookies.set(main.SESSION_COOKIE, main.create_session_token("admin"))
    return client


async def test_presentation_get_default(monkeypatch):
    state_engine = await _setup(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with _admin_client(transport) as admin:
            resp = await admin.get("/api/admin/presentation")
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["enabled"] is False
            assert body["config_revision"] == 1
            assert "config" in body
            assert "presets" in body
            assert set(body["presets"].keys()) == {"software", "tutorial"}
    finally:
        await state_engine.dispose()


async def test_presentation_save_and_rollback(monkeypatch):
    state_engine = await _setup(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with _admin_client(transport) as admin:
            first_save = await admin.put(
                "/api/admin/presentation",
                json={
                    "preset": "custom",
                    "home_blocks": [{"type": "featured", "sort_order": 0, "title": "精选"}],
                    "summary": "first config",
                },
            )
            assert first_save.status_code == 200, first_save.text
            assert first_save.json()["config_revision"] == 2
            first_blocks = first_save.json()["config"]["home_blocks"]
            assert first_blocks[0]["type"] == "featured"

            second_save = await admin.put(
                "/api/admin/presentation",
                json={
                    "preset": "custom",
                    "home_blocks": [{"type": "recent", "sort_order": 0, "title": "最近"}],
                    "summary": "second config",
                },
            )
            assert second_save.status_code == 200, second_save.text
            assert second_save.json()["config_revision"] == 3
            assert second_save.json()["config"]["home_blocks"][0]["type"] == "recent"

            current = await admin.get("/api/admin/presentation")
            revisions = current.json()["revisions"]
            assert revisions, "expected at least one history revision"
            target = revisions[0]
            assert target["revision"] == 2

            rollback = await admin.post(
                "/api/admin/presentation/rollback",
                json={"revision_id": target["revision_id"]},
            )
            assert rollback.status_code == 200, rollback.text
            assert rollback.json()["config_revision"] == 4
            rolled_blocks = rollback.json()["config"]["home_blocks"]
            assert rolled_blocks[0]["type"] == "featured"
            assert rolled_blocks[0]["title"] == "精选"
    finally:
        await state_engine.dispose()


async def test_presentation_schema_rejects_invalid_home_blocks(monkeypatch):
    state_engine = await _setup(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with _admin_client(transport) as admin:
            resp = await admin.put(
                "/api/admin/presentation",
                json={"preset": "custom", "home_blocks": [{"type": "evil", "sort_order": 0}]},
            )
            assert resp.status_code == 422, resp.text

            resp2 = await admin.put(
                "/api/admin/presentation",
                json={"preset": "unknown-preset", "home_blocks": []},
            )
            assert resp2.status_code == 422, resp2.text

            resp3 = await admin.put(
                "/api/admin/presentation",
                json={"preset": "custom", "theme_tokens": {"accent_color": "not-a-color", "card_radius": 12}},
            )
            assert resp3.status_code == 422, resp3.text
    finally:
        await state_engine.dispose()


async def test_presentation_apply_preset(monkeypatch):
    state_engine = await _setup(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with _admin_client(transport) as admin:
            software = await admin.post(
                "/api/admin/presentation/apply-preset",
                json={"preset": "software"},
            )
            assert software.status_code == 200, software.text
            sw_cfg = software.json()["config"]
            assert sw_cfg["preset"] == "software"
            assert sw_cfg["home_blocks"][0]["type"] == "category"
            assert any(nav["href"] == "/resources/software" for nav in sw_cfg["navigation"])

            tutorial = await admin.post(
                "/api/admin/presentation/apply-preset",
                json={"preset": "tutorial"},
            )
            assert tutorial.status_code == 200, tutorial.text
            tu_cfg = tutorial.json()["config"]
            assert tu_cfg["preset"] == "tutorial"
            assert tu_cfg["home_blocks"][0]["type"] == "featured"
            assert all(block["type"] != "topic" for block in tu_cfg["home_blocks"])

            unknown = await admin.post(
                "/api/admin/presentation/apply-preset",
                json={"preset": "custom"},
            )
            assert unknown.status_code == 422, unknown.text
    finally:
        await state_engine.dispose()


async def test_presentation_toggle(monkeypatch):
    state_engine = await _setup(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with _admin_client(transport) as admin:
            enabled = await admin.put(
                "/api/admin/presentation/toggle",
                json={"enabled": True},
            )
            assert enabled.status_code == 200, enabled.text
            assert enabled.json()["enabled"] is True

            current = await admin.get("/api/admin/presentation")
            assert current.json()["enabled"] is True
            assert current.json()["config"]["preset"] == "software"

            disabled = await admin.put(
                "/api/admin/presentation/toggle",
                json={"enabled": False},
            )
            assert disabled.status_code == 200, disabled.text
            assert disabled.json()["enabled"] is False

            after = await admin.get("/api/admin/presentation")
            assert after.json()["enabled"] is False
    finally:
        await state_engine.dispose()
