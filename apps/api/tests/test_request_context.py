from fastapi import Request, Response

from cloudsite import auth, request_context
from cloudsite.config import Settings
from cloudsite.request_context import request_host, request_is_https, request_scheme
from cloudsite.sessions import USER_SESSION_COOKIE, set_user_session_cookie


def make_request(
    peer: str,
    *,
    scheme: str = "http",
    host: str = "testserver",
    forwarded_proto: str | None = None,
    forwarded_host: str | None = None,
    origin: str | None = None,
) -> Request:
    headers = [(b"host", host.encode())]
    for name, value in (
        (b"x-forwarded-proto", forwarded_proto),
        (b"x-forwarded-host", forwarded_host),
        (b"origin", origin),
    ):
        if value is not None:
            headers.append((name, value.encode()))
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


def test_untrusted_peer_cannot_spoof_forwarded_origin_or_secure_cookie(monkeypatch):
    monkeypatch.setattr(request_context.settings, "trusted_proxy_cidrs", "127.0.0.1/32")
    request = make_request(
        "203.0.113.9",
        forwarded_proto="https",
        forwarded_host="evil.example",
    )
    assert request_scheme(request) == "http"
    assert request_host(request) == "testserver"
    assert request_is_https(request) is False
    response = Response()
    set_user_session_cookie(request, response, "token")
    assert f"{USER_SESSION_COOKIE}=token" in response.headers["set-cookie"]
    assert "Secure" not in response.headers["set-cookie"]


def test_trusted_proxy_controls_external_scheme_and_host(monkeypatch):
    monkeypatch.setattr(request_context.settings, "trusted_proxy_cidrs", "127.0.0.1/32")
    request = make_request(
        "127.0.0.1",
        forwarded_proto="https",
        forwarded_host="cloud.example",
        origin="https://cloud.example",
    )
    assert request_scheme(request) == "https"
    assert request_host(request) == "cloud.example"
    assert request_is_https(request) is True
    auth.validate_request_origin(request)
    response = Response()
    set_user_session_cookie(request, response, "token")
    assert "Secure" in response.headers["set-cookie"]


def test_untrusted_forwarded_host_does_not_bypass_origin_check(monkeypatch):
    monkeypatch.setattr(request_context.settings, "trusted_proxy_cidrs", "127.0.0.1/32")
    request = make_request(
        "203.0.113.9",
        forwarded_proto="https",
        forwarded_host="evil.example",
        origin="https://evil.example",
    )
    try:
        auth.validate_request_origin(request)
    except Exception as exc:
        assert getattr(exc, "detail", {}).get("code") == "CSRF_ORIGIN_INVALID"
    else:
        raise AssertionError("untrusted forwarded host bypassed origin validation")


def test_credentialed_cors_rejects_wildcard():
    configured = Settings(cors_origins="*")
    try:
        _ = configured.cors_origin_list
    except ValueError as exc:
        assert "不能包含通配符" in str(exc)
    else:
        raise AssertionError("credentialed CORS accepted wildcard origin")
