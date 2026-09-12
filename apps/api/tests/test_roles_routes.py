"""T1 roles admin route end-to-end tests.

Covers: list roles/permissions, list user roles, update user role,
invalid role rejection, non-existent user, admin auth required.
"""
from __future__ import annotations

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import auth, main
from cloudsite.database import IndexBase, StateBase
from cloudsite.models import SiteSettings, SystemSetting, User, utcnow

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
        state.add(User(
            id=1, username="alice", username_normalized="alice",
            password_hash="x", status="active", role="viewer",
            created_at=utcnow(), updated_at=utcnow(),
        ))
        state.add(User(
            id=2, username="bob", username_normalized="bob",
            password_hash="x", status="active", role="editor",
            created_at=utcnow(), updated_at=utcnow(),
        ))
        await state.commit()

    transport = httpx.ASGITransport(app=main.app)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    return client, state_factory


async def test_list_roles(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        resp = await client.get("/api/admin/roles", headers=ORIGIN, cookies=_admin_cookies())
        assert resp.status_code == 200
        data = resp.json()
        assert "viewer" in data["roles"]
        assert "owner" in data["roles"]
        assert len(data["permissions"]) == 5
    finally:
        await client.aclose()


async def test_list_user_roles(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        resp = await client.get("/api/admin/roles/users", headers=ORIGIN, cookies=_admin_cookies())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["users"]) == 2
        assert data["users"][0]["username"] == "alice"
        assert data["users"][0]["role"] == "viewer"
    finally:
        await client.aclose()


async def test_update_user_role(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        resp = await client.put("/api/admin/roles/users/1", json={
            "role": "editor",
        }, headers=ORIGIN, cookies=_admin_cookies())
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == 1
        assert data["role"] == "editor"
    finally:
        await client.aclose()


async def test_update_user_role_invalid(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        resp = await client.put("/api/admin/roles/users/1", json={
            "role": "superadmin",
        }, headers=ORIGIN, cookies=_admin_cookies())
        assert resp.status_code == 400
    finally:
        await client.aclose()


async def test_update_user_role_not_found(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        resp = await client.put("/api/admin/roles/users/999", json={
            "role": "editor",
        }, headers=ORIGIN, cookies=_admin_cookies())
        assert resp.status_code == 404
    finally:
        await client.aclose()


async def test_admin_auth_required(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        resp = await client.get("/api/admin/roles", headers=ORIGIN)
        assert resp.status_code == 403
    finally:
        await client.aclose()