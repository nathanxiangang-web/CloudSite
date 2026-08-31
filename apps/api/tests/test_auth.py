from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import auth, users
from cloudsite.database import StateBase
from cloudsite.models import User, UserSession
from cloudsite.sessions import USER_SESSION_COOKIE, hash_session_token


ORIGIN = {"Origin": "http://testserver"}


@asynccontextmanager
async def auth_client(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)
    monkeypatch.setattr(auth, "StateSession", factory)
    monkeypatch.setattr(users, "StateSession", factory)
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(users.router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client, factory
    await engine.dispose()


async def register(client: httpx.AsyncClient, username: str = "Nathan", password: str = "password123"):
    return await client.post(
        "/api/auth/register",
        json={"username": username, "password": password, "password_confirm": password},
        headers=ORIGIN,
    )


async def test_register_creates_argon2_user_and_logs_in(monkeypatch):
    async with auth_client(monkeypatch) as (client, factory):
        response = await register(client)
        assert response.status_code == 201
        assert response.json()["username"] == "Nathan"
        assert USER_SESSION_COOKIE in response.cookies
        async with factory() as session:
            user = await session.scalar(select(User))
            assert user is not None
            assert user.password_hash != "password123"
            assert user.password_hash.startswith("$argon2id$")
        me = await client.get("/api/auth/me")
        assert me.json()["authenticated"] is True
        assert me.json()["user"]["username"] == "Nathan"


async def test_duplicate_username(monkeypatch):
    async with auth_client(monkeypatch) as (client, _):
        assert (await register(client, "nathan")).status_code == 201
        duplicate = await register(client, "nathan")
        assert duplicate.status_code == 409
        assert duplicate.json()["detail"]["code"] == "USERNAME_EXISTS"


async def test_case_insensitive_duplicate_username(monkeypatch):
    async with auth_client(monkeypatch) as (client, _):
        assert (await register(client, "Nathan")).status_code == 201
        duplicate = await register(client, "NATHAN")
        assert duplicate.status_code == 409
        assert duplicate.json()["detail"]["code"] == "USERNAME_EXISTS"


async def test_username_and_password_rules(monkeypatch):
    async with auth_client(monkeypatch) as (client, _):
        bad_name = await register(client, " bad name ")
        assert bad_name.status_code == 400
        assert bad_name.json()["detail"]["code"] == "USERNAME_INVALID"
        bad_password = await register(client, "valid_name", "short")
        assert bad_password.status_code == 400
        assert bad_password.json()["detail"]["code"] == "PASSWORD_INVALID"


async def test_login_success_is_case_insensitive(monkeypatch):
    async with auth_client(monkeypatch) as (client, _):
        await register(client, "Nathan")
        await client.post("/api/auth/logout", headers=ORIGIN)
        response = await client.post(
            "/api/auth/login",
            json={"username": "NATHAN", "password": "password123"},
            headers=ORIGIN,
        )
        assert response.status_code == 200
        assert response.json()["username"] == "Nathan"


async def test_login_wrong_password_is_generic(monkeypatch):
    async with auth_client(monkeypatch) as (client, _):
        await register(client)
        await client.post("/api/auth/logout", headers=ORIGIN)
        response = await client.post(
            "/api/auth/login",
            json={"username": "Nathan", "password": "wrong-password"},
            headers=ORIGIN,
        )
        assert response.status_code == 401
        assert response.json()["detail"] == {"code": "INVALID_CREDENTIALS", "message": "用户名或密码错误"}


async def test_logout_revokes_current_session(monkeypatch):
    async with auth_client(monkeypatch) as (client, factory):
        await register(client)
        response = await client.post("/api/auth/logout", headers=ORIGIN)
        assert response.status_code == 200
        assert (await client.get("/api/auth/me")).json() == {"authenticated": False, "user": None}
        async with factory() as session:
            active = await session.scalar(
                select(func.count()).select_from(UserSession).where(UserSession.revoked_at.is_(None))
            )
            assert active == 0


async def test_me_logged_out(monkeypatch):
    async with auth_client(monkeypatch) as (client, _):
        response = await client.get("/api/auth/me")
        assert response.status_code == 200
        assert response.json() == {"authenticated": False, "user": None}


async def test_disabled_user_cannot_login_and_sessions_are_revoked(monkeypatch):
    async with auth_client(monkeypatch) as (client, factory):
        registered = await register(client)
        user_id = registered.json()["id"]
        disabled = await client.patch(
            f"/api/admin/users/{user_id}/status",
            json={"status": "disabled"},
            headers=ORIGIN,
        )
        assert disabled.status_code == 200
        assert disabled.json()["status"] == "disabled"
        assert (await client.get("/api/auth/me")).json()["authenticated"] is False
        login = await client.post(
            "/api/auth/login",
            json={"username": "Nathan", "password": "password123"},
            headers=ORIGIN,
        )
        assert login.status_code == 403
        assert login.json()["detail"]["code"] == "USER_DISABLED"
        async with factory() as session:
            assert await session.scalar(
                select(func.count()).select_from(UserSession).where(UserSession.revoked_at.is_(None))
            ) == 0


async def test_admin_can_restore_and_search_users(monkeypatch):
    async with auth_client(monkeypatch) as (client, _):
        user_id = (await register(client, "Nathan")).json()["id"]
        await client.patch(
            f"/api/admin/users/{user_id}/status", json={"status": "disabled"}, headers=ORIGIN
        )
        filtered = await client.get("/api/admin/users?search=nat&status=disabled")
        assert filtered.status_code == 200
        assert filtered.json()["total"] == 1
        restored = await client.patch(
            f"/api/admin/users/{user_id}/status", json={"status": "active"}, headers=ORIGIN
        )
        assert restored.json()["status"] == "active"
        login = await client.post(
            "/api/auth/login",
            json={"username": "nathan", "password": "password123"},
            headers=ORIGIN,
        )
        assert login.status_code == 200


async def test_change_password_revokes_old_sessions_and_reauthenticates(monkeypatch):
    async with auth_client(monkeypatch) as (client, factory):
        await register(client)
        old_token = client.cookies.get(USER_SESSION_COOKIE)
        changed = await client.post(
            "/api/auth/change-password",
            json={
                "current_password": "password123",
                "new_password": "new-password-456",
                "new_password_confirm": "new-password-456",
            },
            headers=ORIGIN,
        )
        assert changed.status_code == 200
        new_token = client.cookies.get(USER_SESSION_COOKIE)
        assert new_token and new_token != old_token
        async with factory() as session:
            old_row = await session.scalar(
                select(UserSession).where(UserSession.session_token_hash == hash_session_token(old_token))
            )
            assert old_row is not None and old_row.revoked_at is not None
        await client.post("/api/auth/logout", headers=ORIGIN)
        old_login = await client.post(
            "/api/auth/login",
            json={"username": "Nathan", "password": "password123"},
            headers=ORIGIN,
        )
        assert old_login.status_code == 401
        new_login = await client.post(
            "/api/auth/login",
            json={"username": "Nathan", "password": "new-password-456"},
            headers=ORIGIN,
        )
        assert new_login.status_code == 200


async def test_change_password_rejects_wrong_current_password(monkeypatch):
    async with auth_client(monkeypatch) as (client, _):
        await register(client)
        response = await client.post(
            "/api/auth/change-password",
            json={
                "current_password": "wrong-password",
                "new_password": "new-password-456",
                "new_password_confirm": "new-password-456",
            },
            headers=ORIGIN,
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "CURRENT_PASSWORD_INVALID"


async def test_cross_origin_writes_are_rejected(monkeypatch):
    async with auth_client(monkeypatch) as (client, _):
        response = await client.post(
            "/api/auth/register",
            json={"username": "Nathan", "password": "password123", "password_confirm": "password123"},
            headers={"Origin": "https://attacker.example"},
        )
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "CSRF_ORIGIN_INVALID"
