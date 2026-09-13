"""X1 连接管理路由端到端测试。"""
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


async def test_list_connections_empty(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        resp = await client.get("/api/admin/connections", headers=ORIGIN, cookies=_admin_cookies())
        assert resp.status_code == 200
        assert resp.json()["items"] == []
    finally:
        await client.aclose()


async def test_create_and_get_connection(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        resp = await client.post("/api/admin/connections", json={
            "name": "第二来源",
            "base_url": "https://alist2.example.com",
            "username": "admin",
            "password": "secret",
        }, headers=ORIGIN, cookies=_admin_cookies())
        assert resp.status_code == 200
        conn_id = resp.json()["connection_id"]

        resp = await client.get(f"/api/admin/connections/{conn_id}", headers=ORIGIN, cookies=_admin_cookies())
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "第二来源"
        assert data["base_url"] == "https://alist2.example.com"
        assert data["enabled"] is False
    finally:
        await client.aclose()


async def test_toggle_connection(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        resp = await client.post("/api/admin/connections", json={
            "name": "conn1",
            "base_url": "https://a.com",
            "username": "u",
            "password": "p",
        }, headers=ORIGIN, cookies=_admin_cookies())
        conn_id = resp.json()["connection_id"]

        resp = await client.patch(f"/api/admin/connections/{conn_id}/enabled", json={"enabled": True}, headers=ORIGIN, cookies=_admin_cookies())
        assert resp.status_code == 200

        resp = await client.get("/api/admin/connections", headers=ORIGIN, cookies=_admin_cookies())
        assert resp.json()["items"][0]["enabled"] is True
    finally:
        await client.aclose()


async def test_delete_connection(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        await client.post("/api/admin/connections", json={
            "name": "conn0",
            "base_url": "https://a0.com",
            "username": "u",
            "password": "p",
        }, headers=ORIGIN, cookies=_admin_cookies())

        resp = await client.post("/api/admin/connections", json={
            "name": "conn1",
            "base_url": "https://a.com",
            "username": "u",
            "password": "p",
        }, headers=ORIGIN, cookies=_admin_cookies())
        conn_id = resp.json()["connection_id"]

        resp = await client.delete(f"/api/admin/connections/{conn_id}", headers=ORIGIN, cookies=_admin_cookies())
        assert resp.status_code == 200

        resp = await client.get(f"/api/admin/connections/{conn_id}", headers=ORIGIN, cookies=_admin_cookies())
        assert resp.status_code == 404
    finally:
        await client.aclose()


async def test_compat_records(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        resp = await client.post("/api/admin/connections/compat-records", json={
            "provider_type": "generic_alist",
            "adapter_version": "generic_alist@1",
            "platform": "alist-v3",
            "platform_version": "3.25.0",
            "test_result": "pass",
            "notes": "全部能力正常",
        }, headers=ORIGIN, cookies=_admin_cookies())
        assert resp.status_code == 200

        resp = await client.get("/api/admin/connections/compat-records", headers=ORIGIN, cookies=_admin_cookies())
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1
    finally:
        await client.aclose()


async def test_connection_not_found(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        resp = await client.get("/api/admin/connections/999", headers=ORIGIN, cookies=_admin_cookies())
        assert resp.status_code == 404
    finally:
        await client.aclose()