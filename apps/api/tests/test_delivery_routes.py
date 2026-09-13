"""T2 delivery package route end-to-end tests.

Covers: admin CRUD (create, list, detail, add item, publish, cancel, export),
client view (with/without access code), client feedback, admin auth required.
"""
from __future__ import annotations

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import auth, main
from cloudsite.database import IndexBase, StateBase
from cloudsite.models import SiteSettings, SystemSetting, utcnow

ORIGIN = {"Origin": "http://testserver"}


def _admin_cookies():
    return {main.SESSION_COOKIE: main.create_session_token("admin")}


async def _setup(monkeypatch):
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
        state.add(SystemSetting(key="setup_completed", value="true", value_type="string"))
        await state.commit()

    transport = httpx.ASGITransport(app=main.app)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    return client, state_factory


async def test_create_package(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        resp = await client.post("/api/admin/delivery-packages", json={
            "name": "Test Package",
            "project_note": "A test delivery",
        }, headers=ORIGIN, cookies=_admin_cookies())
        assert resp.status_code == 200
        data = resp.json()
        assert data["package_id"].startswith("dp_")
        assert data["status"] == "draft"
    finally:
        await client.aclose()


async def test_list_packages(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        await client.post("/api/admin/delivery-packages", json={"name": "A"}, headers=ORIGIN, cookies=_admin_cookies())
        await client.post("/api/admin/delivery-packages", json={"name": "B"}, headers=ORIGIN, cookies=_admin_cookies())

        resp = await client.get("/api/admin/delivery-packages", headers=ORIGIN, cookies=_admin_cookies())
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
    finally:
        await client.aclose()


async def test_get_package_detail(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        create_resp = await client.post("/api/admin/delivery-packages", json={"name": "Test"}, headers=ORIGIN, cookies=_admin_cookies())
        package_id = create_resp.json()["package_id"]

        await client.post(f"/api/admin/delivery-packages/{package_id}/items", json={
            "display_name": "Item 1",
        }, headers=ORIGIN, cookies=_admin_cookies())

        resp = await client.get(f"/api/admin/delivery-packages/{package_id}", headers=ORIGIN, cookies=_admin_cookies())
        assert resp.status_code == 200
        data = resp.json()
        assert data["package"]["name"] == "Test"
        assert len(data["items"]) == 1
    finally:
        await client.aclose()


async def test_publish_and_view(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        create_resp = await client.post("/api/admin/delivery-packages", json={"name": "Pub Test"}, headers=ORIGIN, cookies=_admin_cookies())
        package_id = create_resp.json()["package_id"]
        access_token = create_resp.json().get("access_token", "")

        pub_resp = await client.post(f"/api/admin/delivery-packages/{package_id}/publish", headers=ORIGIN, cookies=_admin_cookies())
        assert pub_resp.status_code == 200
        assert pub_resp.json()["status"] == "published"

        detail_resp = await client.get(f"/api/admin/delivery-packages/{package_id}", headers=ORIGIN, cookies=_admin_cookies())
        access_token = None
        for item in detail_resp.json().get("items", []):
            pass

        from cloudsite.models import DeliveryPackage
        from sqlalchemy import select
        async with main.StateSession() as state:
            pkg = (await state.execute(select(DeliveryPackage).where(DeliveryPackage.package_id == package_id))).scalar_one()
            access_token = pkg.access_token

        view_resp = await client.get(f"/api/delivery/{access_token}", headers=ORIGIN)
        assert view_resp.status_code == 200
        assert view_resp.json()["package"]["name"] == "Pub Test"
    finally:
        await client.aclose()


async def test_cancel_package(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        create_resp = await client.post("/api/admin/delivery-packages", json={"name": "Cancel Test"}, headers=ORIGIN, cookies=_admin_cookies())
        package_id = create_resp.json()["package_id"]

        resp = await client.post(f"/api/admin/delivery-packages/{package_id}/cancel", headers=ORIGIN, cookies=_admin_cookies())
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"
    finally:
        await client.aclose()


async def test_export_package(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        create_resp = await client.post("/api/admin/delivery-packages", json={"name": "Export Test"}, headers=ORIGIN, cookies=_admin_cookies())
        package_id = create_resp.json()["package_id"]

        resp = await client.get(f"/api/admin/delivery-packages/{package_id}/export", headers=ORIGIN, cookies=_admin_cookies())
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["name"] == "Export Test"
    finally:
        await client.aclose()


async def test_client_view_draft_denied(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        create_resp = await client.post("/api/admin/delivery-packages", json={"name": "Draft"}, headers=ORIGIN, cookies=_admin_cookies())
        package_id = create_resp.json()["package_id"]

        from cloudsite.models import DeliveryPackage
        from sqlalchemy import select
        async with main.StateSession() as state:
            pkg = (await state.execute(select(DeliveryPackage).where(DeliveryPackage.package_id == package_id))).scalar_one()
            access_token = pkg.access_token

        resp = await client.get(f"/api/delivery/{access_token}", headers=ORIGIN)
        assert resp.status_code == 403
    finally:
        await client.aclose()


async def test_client_feedback(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        create_resp = await client.post("/api/admin/delivery-packages", json={"name": "Feedback Test"}, headers=ORIGIN, cookies=_admin_cookies())
        package_id = create_resp.json()["package_id"]
        await client.post(f"/api/admin/delivery-packages/{package_id}/publish", headers=ORIGIN, cookies=_admin_cookies())

        from cloudsite.models import DeliveryPackage
        from sqlalchemy import select
        async with main.StateSession() as state:
            pkg = (await state.execute(select(DeliveryPackage).where(DeliveryPackage.package_id == package_id))).scalar_one()
            access_token = pkg.access_token

        resp = await client.post(f"/api/delivery/{access_token}/feedback", json={
            "kind": "confirmed",
            "message": "All files received",
        }, headers=ORIGIN)
        assert resp.status_code == 200
    finally:
        await client.aclose()


async def test_admin_auth_required(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        resp = await client.get("/api/admin/delivery-packages", headers=ORIGIN)
        assert resp.status_code == 403
    finally:
        await client.aclose()


async def test_package_not_found(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        resp = await client.get("/api/admin/delivery-packages/dp_nonexistent", headers=ORIGIN, cookies=_admin_cookies())
        assert resp.status_code == 404
    finally:
        await client.aclose()


async def test_client_feedback_protected_with_code(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        create_resp = await client.post("/api/admin/delivery-packages", json={
            "name": "Protected Feedback",
            "access_code": "secret123",
        }, headers=ORIGIN, cookies=_admin_cookies())
        package_id = create_resp.json()["package_id"]
        await client.post(f"/api/admin/delivery-packages/{package_id}/publish", headers=ORIGIN, cookies=_admin_cookies())

        from cloudsite.models import DeliveryPackage
        from sqlalchemy import select
        async with main.StateSession() as state:
            pkg = (await state.execute(select(DeliveryPackage).where(DeliveryPackage.package_id == package_id))).scalar_one()
            access_token = pkg.access_token

        resp = await client.post(f"/api/delivery/{access_token}/feedback", json={
            "kind": "confirmed",
            "message": "Received with code",
        }, params={"code": "secret123"}, headers=ORIGIN)
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
    finally:
        await client.aclose()


async def test_client_feedback_protected_without_code(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        create_resp = await client.post("/api/admin/delivery-packages", json={
            "name": "Protected Feedback No Code",
            "access_code": "secret123",
        }, headers=ORIGIN, cookies=_admin_cookies())
        package_id = create_resp.json()["package_id"]
        await client.post(f"/api/admin/delivery-packages/{package_id}/publish", headers=ORIGIN, cookies=_admin_cookies())

        from cloudsite.models import DeliveryPackage
        from sqlalchemy import select
        async with main.StateSession() as state:
            pkg = (await state.execute(select(DeliveryPackage).where(DeliveryPackage.package_id == package_id))).scalar_one()
            access_token = pkg.access_token

        resp = await client.post(f"/api/delivery/{access_token}/feedback", json={
            "kind": "confirmed",
            "message": "Missing code",
        }, headers=ORIGIN)
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "ACCESS_DENIED"
    finally:
        await client.aclose()


async def test_client_feedback_protected_wrong_code(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        create_resp = await client.post("/api/admin/delivery-packages", json={
            "name": "Protected Feedback Wrong Code",
            "access_code": "secret123",
        }, headers=ORIGIN, cookies=_admin_cookies())
        package_id = create_resp.json()["package_id"]
        await client.post(f"/api/admin/delivery-packages/{package_id}/publish", headers=ORIGIN, cookies=_admin_cookies())

        from cloudsite.models import DeliveryPackage
        from sqlalchemy import select
        async with main.StateSession() as state:
            pkg = (await state.execute(select(DeliveryPackage).where(DeliveryPackage.package_id == package_id))).scalar_one()
            access_token = pkg.access_token

        resp = await client.post(f"/api/delivery/{access_token}/feedback", json={
            "kind": "confirmed",
            "message": "Wrong code",
        }, params={"code": "wrong-code"}, headers=ORIGIN)
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "ACCESS_DENIED"
    finally:
        await client.aclose()
