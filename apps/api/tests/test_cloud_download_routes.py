"""Focused route tests for /api/cloud-download/tasks.

Covers: valid submit, invalid URL, anonymous rejection, origin rejection,
per-user ownership isolation, rate limit, absent task in CLI list, and
CLI unavailable. The 115driver adapter is mocked in every test; no real
downloads or credentials are involved.
"""
from __future__ import annotations

from datetime import timedelta

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import auth, main
from cloudsite.database import StateBase
from cloudsite.models import SiteSettings, SystemSetting, User, utcnow
from cloudsite.plugins.ai.services import cloud_download as cd_service
from cloudsite.plugins.ai.services.cloud_download_driver import AddOfflineResult, CloudDownloadError, OfflineTask
from cloudsite.sessions import USER_SESSION_COOKIE, create_user_session

ORIGIN = {"Origin": "http://testserver"}
BAD_ORIGIN = {"Origin": "http://evil.example"}


async def _setup(monkeypatch):
    """Build an in-memory state DB and an ASGI client against main.app."""
    state_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    async with state_factory() as state:
        state.add(SiteSettings(id=1))
        state.add(SystemSetting(key="setup_completed", value="true", value_type="string"))
        await state.commit()
    monkeypatch.setattr(main, "StateSession", state_factory)
    monkeypatch.setattr(auth, "StateSession", state_factory)
    transport = httpx.ASGITransport(app=main.app)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    return client, state_factory, state_engine


async def _make_user(factory, username: str) -> tuple[User, str]:
    """Create an active user and return (user, session_token)."""
    async with factory() as state:
        now = utcnow()
        user = User(
            username=username,
            username_normalized=username.lower(),
            password_hash=auth.password_hash.hash(f"{username}-pass-123"),
            status="active",
            created_at=now,
            updated_at=now,
        )
        state.add(user)
        await state.flush()
        _, token = await create_user_session(state, user.id, now)
        await state.commit()
        return user, token


def _fake_add_ok(hashes: list[str] | None = None):
    async def _add(url: str) -> AddOfflineResult:
        return AddOfflineResult(hashes=hashes if hashes is not None else ["hash-1"], save_dir="/\u4e91\u4e0b\u8f7d")

    return _add


def _fake_list_ok(tasks: list[OfflineTask]):
    async def _list() -> list[OfflineTask]:
        return tasks

    return _list


def _fake_list_unavailable():
    async def _list() -> list[OfflineTask]:
        raise CloudDownloadError("CD-002", "CLI not available")

    return _list


def _cookies(token: str) -> dict:
    return {USER_SESSION_COOKIE: token}


# --- valid submit ---------------------------------------------------------

async def test_valid_submit(monkeypatch):
    monkeypatch.setattr(cd_service, "add_offline_task", _fake_add_ok(["hash-1"]))
    client, factory, engine = await _setup(monkeypatch)
    try:
        _, token = await _make_user(factory, "alice")
        resp = await client.post(
            "/api/cloud-download/tasks",
            json={"url": "https://example.com/file.zip"},
            headers=ORIGIN,
            cookies=_cookies(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] > 0
        assert data["status"] == "submitted"
        assert data["percent"] == 0.0
        assert "created_at" in data
        assert "https://example.com" not in data["name"]
    finally:
        await client.aclose()
        await engine.dispose()


# --- invalid URL ----------------------------------------------------------

async def test_invalid_url_rejected(monkeypatch):
    # Do not mock add_offline_task: the real validate_url rejects before any CLI call.
    client, factory, engine = await _setup(monkeypatch)
    try:
        _, token = await _make_user(factory, "alice")
        resp = await client.post(
            "/api/cloud-download/tasks",
            json={"url": "ftp://example.com/file"},
            headers=ORIGIN,
            cookies=_cookies(token),
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "CD_URL_INVALID"
    finally:
        await client.aclose()
        await engine.dispose()


# --- anonymous rejection --------------------------------------------------

async def test_anonymous_rejected(monkeypatch):
    monkeypatch.setattr(cd_service, "add_offline_task", _fake_add_ok())
    client, _factory, engine = await _setup(monkeypatch)
    try:
        post_resp = await client.post(
            "/api/cloud-download/tasks",
            json={"url": "https://example.com/file.zip"},
            headers=ORIGIN,
        )
        assert post_resp.status_code == 401
        assert post_resp.json()["detail"]["code"] == "AUTH_REQUIRED"
        get_resp = await client.get("/api/cloud-download/tasks", headers=ORIGIN)
        assert get_resp.status_code == 401
        assert get_resp.json()["detail"]["code"] == "AUTH_REQUIRED"
    finally:
        await client.aclose()
        await engine.dispose()


# --- origin rejection -----------------------------------------------------

async def test_bad_origin_rejected(monkeypatch):
    monkeypatch.setattr(cd_service, "add_offline_task", _fake_add_ok())
    client, factory, engine = await _setup(monkeypatch)
    try:
        _, token = await _make_user(factory, "alice")
        resp = await client.post(
            "/api/cloud-download/tasks",
            json={"url": "https://example.com/file.zip"},
            headers=BAD_ORIGIN,
            cookies=_cookies(token),
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "CSRF_ORIGIN_INVALID"
    finally:
        await client.aclose()
        await engine.dispose()


# --- per-user ownership isolation -----------------------------------------

async def test_ownership_isolation(monkeypatch):
    monkeypatch.setattr(cd_service, "add_offline_task", _fake_add_ok(["hash-alice"]))
    client, factory, engine = await _setup(monkeypatch)
    try:
        alice, alice_token = await _make_user(factory, "alice")
        bob, bob_token = await _make_user(factory, "bob")
        await client.post(
            "/api/cloud-download/tasks",
            json={"url": "https://example.com/a.zip"},
            headers=ORIGIN,
            cookies=_cookies(alice_token),
        )
        monkeypatch.setattr(cd_service, "add_offline_task", _fake_add_ok(["hash-bob"]))
        await client.post(
            "/api/cloud-download/tasks",
            json={"url": "https://example.com/b.zip"},
            headers=ORIGIN,
            cookies=_cookies(bob_token),
        )
        monkeypatch.setattr(cd_service, "list_offline_tasks", _fake_list_ok([]))
        alice_resp = await client.get("/api/cloud-download/tasks", headers=ORIGIN, cookies=_cookies(alice_token))
        assert alice_resp.status_code == 200
        alice_items = alice_resp.json()["items"]
        assert len(alice_items) == 1
        assert alice_items[0]["id"] != 0
        bob_resp = await client.get("/api/cloud-download/tasks", headers=ORIGIN, cookies=_cookies(bob_token))
        bob_items = bob_resp.json()["items"]
        assert len(bob_items) == 1
        assert bob_items[0]["id"] != alice_items[0]["id"]
    finally:
        await client.aclose()
        await engine.dispose()


# --- rate limit -----------------------------------------------------------

async def test_rate_limit_enforced(monkeypatch):
    monkeypatch.setattr(cd_service, "add_offline_task", _fake_add_ok())
    client, factory, engine = await _setup(monkeypatch)
    try:
        _, token = await _make_user(factory, "alice")
        for i in range(cd_service.DAILY_SUBMISSION_LIMIT):
            resp = await client.post(
                "/api/cloud-download/tasks",
                json={"url": f"https://example.com/file{i}.zip"},
                headers=ORIGIN,
                cookies=_cookies(token),
            )
            assert resp.status_code == 200, f"submit {i} failed: {resp.text}"
        over = await client.post(
            "/api/cloud-download/tasks",
            json={"url": "https://example.com/over.zip"},
            headers=ORIGIN,
            cookies=_cookies(token),
        )
        assert over.status_code == 429
        assert over.json()["detail"]["code"] == "CD_RATE_LIMIT"
    finally:
        await client.aclose()
        await engine.dispose()


# --- absent task in CLI list keeps neutral status -------------------------

async def test_absent_task_in_cli_list_keeps_neutral(monkeypatch):
    monkeypatch.setattr(cd_service, "add_offline_task", _fake_add_ok(["hash-missing"]))
    client, factory, engine = await _setup(monkeypatch)
    try:
        _, token = await _make_user(factory, "alice")
        await client.post(
            "/api/cloud-download/tasks",
            json={"url": "https://example.com/file.zip"},
            headers=ORIGIN,
            cookies=_cookies(token),
        )
        monkeypatch.setattr(
            cd_service,
            "list_offline_tasks",
            _fake_list_ok([OfflineTask(hash="hash-other", name="other.zip", status="running", percent=10.0, size=100)]),
        )
        resp = await client.get("/api/cloud-download/tasks", headers=ORIGIN, cookies=_cookies(token))
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["status"] == "submitted"
        assert items[0]["percent"] == 0.0
        assert items[0]["name"] == cd_service.DEFAULT_DISPLAY_NAME
    finally:
        await client.aclose()
        await engine.dispose()


# --- CLI unavailable on GET keeps neutral status --------------------------

async def test_cli_unavailable_on_get_keeps_neutral(monkeypatch):
    monkeypatch.setattr(cd_service, "add_offline_task", _fake_add_ok(["hash-1"]))
    client, factory, engine = await _setup(monkeypatch)
    try:
        _, token = await _make_user(factory, "alice")
        await client.post(
            "/api/cloud-download/tasks",
            json={"url": "https://example.com/file.zip"},
            headers=ORIGIN,
            cookies=_cookies(token),
        )
        monkeypatch.setattr(cd_service, "list_offline_tasks", _fake_list_unavailable())
        resp = await client.get("/api/cloud-download/tasks", headers=ORIGIN, cookies=_cookies(token))
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["status"] == "submitted"
    finally:
        await client.aclose()
        await engine.dispose()


# --- CLI unavailable on POST surfaces a sanitized error -------------------

async def test_cli_unavailable_on_post_sanitized(monkeypatch):
    async def _add_unavailable(url: str) -> AddOfflineResult:
        raise CloudDownloadError("CD-002", "CLI not available")

    monkeypatch.setattr(cd_service, "add_offline_task", _add_unavailable)
    client, factory, engine = await _setup(monkeypatch)
    try:
        _, token = await _make_user(factory, "alice")
        resp = await client.post(
            "/api/cloud-download/tasks",
            json={"url": "https://example.com/file.zip"},
            headers=ORIGIN,
            cookies=_cookies(token),
        )
        assert resp.status_code == 503
        assert resp.json()["detail"]["code"] == "CD_CLI_UNAVAILABLE"
    finally:
        await client.aclose()
        await engine.dispose()


# --- response never leaks hash or URL -------------------------------------

async def test_response_never_leaks_hash_or_url(monkeypatch):
    secret_url = "https://example.com/secret-path/file.zip"
    monkeypatch.setattr(cd_service, "add_offline_task", _fake_add_ok(["secret-hash"]))
    client, factory, engine = await _setup(monkeypatch)
    try:
        _, token = await _make_user(factory, "alice")
        post_resp = await client.post(
            "/api/cloud-download/tasks",
            json={"url": secret_url},
            headers=ORIGIN,
            cookies=_cookies(token),
        )
        assert post_resp.status_code == 200
        body = post_resp.json()
        assert "secret-hash" not in str(body)
        assert "secret-path" not in str(body)
        assert secret_url not in str(body)
        monkeypatch.setattr(
            cd_service,
            "list_offline_tasks",
            _fake_list_ok([OfflineTask(hash="secret-hash", name="file.zip", status="done", percent=100.0, size=1024)]),
        )
        get_resp = await client.get("/api/cloud-download/tasks", headers=ORIGIN, cookies=_cookies(token))
        assert get_resp.status_code == 200
        get_body = get_resp.json()
        assert "secret-hash" not in str(get_body)
        assert "secret-path" not in str(get_body)
        assert secret_url not in str(get_body)
    finally:
        await client.aclose()
        await engine.dispose()
