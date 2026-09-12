"""X2 API Token + Webhook admin route end-to-end tests."""
from __future__ import annotations

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import auth, main
from cloudsite.database import IndexBase, StateBase
from cloudsite.models import SiteSettings, SystemSetting

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


async def test_create_token(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        resp = await client.post("/api/admin/api-tokens", json={
            "label": "test-token",
            "scopes": ["entry:read"],
        }, headers=ORIGIN, cookies=_admin_cookies())
        assert resp.status_code == 200
        data = resp.json()
        assert data["token_id"].startswith("at_")
        assert len(data["raw_token"]) > 0
    finally:
        await client.aclose()


async def test_list_tokens(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        await client.post("/api/admin/api-tokens", json={"label": "A"}, headers=ORIGIN, cookies=_admin_cookies())
        await client.post("/api/admin/api-tokens", json={"label": "B"}, headers=ORIGIN, cookies=_admin_cookies())

        resp = await client.get("/api/admin/api-tokens", headers=ORIGIN, cookies=_admin_cookies())
        assert resp.status_code == 200
        assert len(resp.json()["tokens"]) == 2
    finally:
        await client.aclose()


async def test_revoke_token(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        create_resp = await client.post("/api/admin/api-tokens", json={"label": "test"}, headers=ORIGIN, cookies=_admin_cookies())
        token_id = create_resp.json()["token_id"]

        resp = await client.delete(f"/api/admin/api-tokens/{token_id}", headers=ORIGIN, cookies=_admin_cookies())
        assert resp.status_code == 200
    finally:
        await client.aclose()


async def test_create_webhook(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        resp = await client.post("/api/admin/webhooks", json={
            "url": "https://example.com/hook",
            "event_types": ["entry.created"],
        }, headers=ORIGIN, cookies=_admin_cookies())
        assert resp.status_code == 200
        data = resp.json()
        assert data["endpoint_id"].startswith("wh_")
    finally:
        await client.aclose()


async def test_list_webhooks(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        await client.post("/api/admin/webhooks", json={"url": "https://a.com"}, headers=ORIGIN, cookies=_admin_cookies())

        resp = await client.get("/api/admin/webhooks", headers=ORIGIN, cookies=_admin_cookies())
        assert resp.status_code == 200
        assert len(resp.json()["endpoints"]) == 1
    finally:
        await client.aclose()


async def test_dispatch_event(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        await client.post("/api/admin/webhooks", json={
            "url": "https://example.com/hook",
            "event_types": ["entry.created"],
        }, headers=ORIGIN, cookies=_admin_cookies())

        resp = await client.post("/api/admin/webhooks/dispatch", json={
            "event_type": "entry.created",
            "event_data": {"entry_id": "e1"},
        }, headers=ORIGIN, cookies=_admin_cookies())
        assert resp.status_code == 200
        assert resp.json()["dispatched_count"] == 1
    finally:
        await client.aclose()


async def test_admin_auth_required(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        resp = await client.get("/api/admin/api-tokens", headers=ORIGIN)
        assert resp.status_code == 403
    finally:
        await client.aclose()