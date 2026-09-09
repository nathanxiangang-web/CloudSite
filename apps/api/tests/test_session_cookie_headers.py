"""24-hour login Set-Cookie contract tests.

These tests lock the 24-hour login lifetime at the real HTTP Set-Cookie
boundary for both normal users and administrators. They exercise the real
cookie-setting helpers and the real administrator login response path, and
they drive HTTPS secure-cookie detection through the repository's existing
trusted-proxy request helpers (request_context.request_is_https) rather than
hardcoded header assumptions.
"""
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import auth, request_context, sessions, users
from cloudsite.database import StateBase
from cloudsite.models import AListConnection, SystemSetting
from cloudsite.routers.admin.auth import router as admin_auth_router
from cloudsite.sessions import USER_SESSION_COOKIE, set_user_session_cookie

USER_COOKIE = USER_SESSION_COOKIE
ADMIN_COOKIE = "cloudsite_session"
EXPECTED_MAX_AGE = "86400"
ORIGIN = {"Origin": "http://testserver"}


def make_request(
    peer: str,
    *,
    scheme: str = "http",
    host: str = "testserver",
    forwarded_proto: str | None = None,
) -> Request:
    """Build a real ASGI Request scope, mirroring test_request_context helpers."""
    headers = [(b"host", host.encode())]
    if forwarded_proto is not None:
        headers.append((b"x-forwarded-proto", forwarded_proto.encode()))
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": scheme,
            "path": "/api/auth/login",
            "raw_path": b"/api/auth/login",
            "query_string": b"",
            "headers": headers,
            "client": (peer, 12345),
            "server": (host, 443 if scheme == "https" else 80),
        }
    )


def parse_cookie(raw: str) -> tuple[str, dict[str, str | bool]]:
    """Parse a Set-Cookie header into (name, attrs).

    Flag attributes (HttpOnly, Secure) map to True; valued attributes
    (Max-Age, Path, SameSite) map to their string value with lower-cased key.
    """
    parts = [p.strip() for p in raw.split(";") if p.strip()]
    name = parts[0].partition("=")[0]
    attrs: dict[str, str | bool] = {}
    for part in parts[1:]:
        if "=" in part:
            key, _, value = part.partition("=")
            attrs[key.lower()] = value
        else:
            attrs[part.lower()] = True
    return name, attrs


def find_cookie(headers: httpx.Headers, cookie_name: str) -> dict[str, str | bool]:
    """Return parsed attrs for the named cookie from an httpx response."""
    for raw in headers.get_list("set-cookie"):
        name, attrs = parse_cookie(raw)
        if name == cookie_name:
            return attrs
    raise AssertionError(f"{cookie_name} not in set-cookie: {headers.get_list('set-cookie')}")


def assert_24h_cookie_attrs(attrs: dict[str, str | bool], *, secure: bool) -> None:
    assert attrs.get("max-age") == EXPECTED_MAX_AGE, attrs
    assert attrs.get("httponly") is True, attrs
    assert attrs.get("samesite") == "lax", attrs
    assert attrs.get("path") == "/", attrs
    if secure:
        assert attrs.get("secure") is True, attrs
    else:
        assert "secure" not in attrs, attrs


# --- Normal-user cookie helper (real set_user_session_cookie) ---


def test_normal_user_cookie_helper_http_attributes():
    request = make_request("203.0.113.9")
    response = Response()
    set_user_session_cookie(request, response, "session-token")
    raw = response.headers["set-cookie"]
    name, attrs = parse_cookie(raw)
    assert name == USER_COOKIE
    assert_24h_cookie_attrs(attrs, secure=False)


def test_normal_user_cookie_helper_https_via_trusted_proxy_sets_secure(monkeypatch):
    monkeypatch.setattr(request_context.settings, "trusted_proxy_cidrs", "127.0.0.1/32")
    request = make_request("127.0.0.1", forwarded_proto="https")
    assert request_context.request_is_https(request) is True
    response = Response()
    set_user_session_cookie(request, response, "session-token")
    raw = response.headers["set-cookie"]
    name, attrs = parse_cookie(raw)
    assert name == USER_COOKIE
    assert_24h_cookie_attrs(attrs, secure=True)


def test_normal_user_cookie_helper_untrusted_peer_cannot_spoof_secure(monkeypatch):
    monkeypatch.setattr(request_context.settings, "trusted_proxy_cidrs", "127.0.0.1/32")
    request = make_request("203.0.113.9", forwarded_proto="https")
    assert request_context.request_is_https(request) is False
    response = Response()
    set_user_session_cookie(request, response, "session-token")
    raw = response.headers["set-cookie"]
    _, attrs = parse_cookie(raw)
    assert_24h_cookie_attrs(attrs, secure=False)


# --- Normal-user login response path (real /api/auth/login) ---


@asynccontextmanager
async def user_auth_client(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)
    monkeypatch.setattr(auth, "StateSession", factory)
    monkeypatch.setattr(users, "StateSession", factory)
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(users.router)
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    await engine.dispose()


async def test_normal_user_login_response_sets_24h_cookie_attributes(monkeypatch):
    async with user_auth_client(monkeypatch) as client:
        await client.post(
            "/api/auth/register",
            json={"username": "Nathan", "password": "password123", "password_confirm": "password123"},
            headers=ORIGIN,
        )
        await client.post("/api/auth/logout", headers=ORIGIN)
        response = await client.post(
            "/api/auth/login",
            json={"username": "Nathan", "password": "password123"},
            headers=ORIGIN,
        )
        assert response.status_code == 200
        attrs = find_cookie(response.headers, USER_COOKIE)
        assert_24h_cookie_attrs(attrs, secure=False)


# --- Administrator login response path (real route, minimal mocks) ---


class _FakeAListClient:
    """Minimal AListClient stand-in: test() always succeeds."""

    def __init__(self, *args, **kwargs):
        pass

    async def test(self):
        return {}


@asynccontextmanager
async def admin_login_client(monkeypatch, *, https: bool):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)
    async with factory() as session:
        session.add(SystemSetting(key="setup_completed", value="true", value_type="string"))
        session.add(AListConnection(id=1, base_url="http://alist.test", enabled=True))
        await session.commit()

    import cloudsite.main as main_module
    import cloudsite.routers.admin.auth as admin_auth_module

    monkeypatch.setattr(main_module, "StateSession", factory)
    monkeypatch.setattr(admin_auth_module, "AListClient", _FakeAListClient)
    monkeypatch.setattr(request_context.settings, "trusted_proxy_cidrs", "127.0.0.1/32")

    app = FastAPI()
    app.include_router(admin_auth_router)
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 12345))
    headers = {}
    if https:
        headers["x-forwarded-proto"] = "https"
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", headers=headers) as client:
        yield client
    await engine.dispose()


async def test_admin_login_response_sets_24h_cookie_attributes(monkeypatch):
    async with admin_login_client(monkeypatch, https=False) as client:
        response = await client.post(
            "/api/admin/auth/login",
            json={"username": "admin", "password": "admin-pass"},
        )
        assert response.status_code == 200
        attrs = find_cookie(response.headers, ADMIN_COOKIE)
        assert_24h_cookie_attrs(attrs, secure=False)


async def test_admin_login_response_https_via_trusted_proxy_sets_secure(monkeypatch):
    async with admin_login_client(monkeypatch, https=True) as client:
        response = await client.post(
            "/api/admin/auth/login",
            json={"username": "admin", "password": "admin-pass"},
        )
        assert response.status_code == 200
        attrs = find_cookie(response.headers, ADMIN_COOKIE)
        assert_24h_cookie_attrs(attrs, secure=True)
