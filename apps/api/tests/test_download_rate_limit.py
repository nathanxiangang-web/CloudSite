import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi import Request
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import download_rate_limit, main
from cloudsite.database import StateBase
from cloudsite.download_rate_limit import (
    DownloadRateDecision,
    check_download_rate,
    get_effective_client_ip,
    hash_ip,
    normalize_ip,
    rate_limit_payload,
)
from cloudsite.models import Resource


BASE_TIME = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


async def rate_store(tmp_path, monkeypatch, name="rate.db"):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / name}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)
    monkeypatch.setattr(download_rate_limit, "StateSession", factory)
    return engine, factory


def request_from(peer: str, forwarded: str | None = None) -> Request:
    headers = [] if forwarded is None else [(b"x-forwarded-for", forwarded.encode())]
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/d/r_test",
            "raw_path": b"/d/r_test",
            "query_string": b"",
            "headers": headers,
            "client": (peer, 12345),
            "server": ("testserver", 80),
        }
    )


async def test_download_first_three_allowed(tmp_path, monkeypatch):
    engine, _ = await rate_store(tmp_path, monkeypatch)
    decisions = [await check_download_rate("203.0.113.10", BASE_TIME + timedelta(seconds=i)) for i in range(3)]
    assert [item.allowed for item in decisions] == [True, True, True]
    await engine.dispose()


async def test_download_fourth_blocked(tmp_path, monkeypatch):
    engine, _ = await rate_store(tmp_path, monkeypatch)
    for offset in (0, 10, 20):
        assert (await check_download_rate("203.0.113.10", BASE_TIME + timedelta(seconds=offset))).allowed
    denied = await check_download_rate("203.0.113.10", BASE_TIME + timedelta(seconds=30))
    assert denied.allowed is False
    assert denied.retry_after == 60
    assert denied.blocked_until == BASE_TIME + timedelta(seconds=90)
    assert rate_limit_payload(denied)["code"] == "DOWNLOAD_RATE_LIMITED"
    await engine.dispose()


async def test_download_retry_after_uses_persisted_remaining_time(tmp_path, monkeypatch):
    engine, _ = await rate_store(tmp_path, monkeypatch)
    for offset in (0, 10, 20, 30):
        decision = await check_download_rate("203.0.113.10", BASE_TIME + timedelta(seconds=offset))
    again = await check_download_rate("203.0.113.10", BASE_TIME + timedelta(seconds=50))
    assert decision.retry_after == 60
    assert again.retry_after == 40
    await engine.dispose()


async def test_refresh_does_not_reset_block(tmp_path, monkeypatch):
    engine, _ = await rate_store(tmp_path, monkeypatch)
    for offset in (0, 10, 20, 30):
        blocked = await check_download_rate("203.0.113.10", BASE_TIME + timedelta(seconds=offset))
    refreshed = await check_download_rate("203.0.113.10", BASE_TIME + timedelta(seconds=61))
    assert refreshed.allowed is False
    assert refreshed.blocked_until == blocked.blocked_until
    assert refreshed.retry_after == 29
    await engine.dispose()


async def test_blocked_retry_does_not_extend_wait(tmp_path, monkeypatch):
    engine, _ = await rate_store(tmp_path, monkeypatch)
    for offset in (0, 10, 20, 30):
        first = await check_download_rate("203.0.113.10", BASE_TIME + timedelta(seconds=offset))
    repeated = [await check_download_rate("203.0.113.10", BASE_TIME + timedelta(seconds=offset)) for offset in (40, 50, 70)]
    assert all(item.blocked_until == first.blocked_until for item in repeated)
    await engine.dispose()


async def test_wait_expires(tmp_path, monkeypatch):
    engine, _ = await rate_store(tmp_path, monkeypatch)
    for offset in (0, 10, 20, 30):
        await check_download_rate("203.0.113.10", BASE_TIME + timedelta(seconds=offset))
    assert (await check_download_rate("203.0.113.10", BASE_TIME + timedelta(seconds=90))).allowed
    await engine.dispose()


async def test_different_ip_independent(tmp_path, monkeypatch):
    engine, _ = await rate_store(tmp_path, monkeypatch)
    for offset in (0, 10, 20, 30):
        blocked = await check_download_rate("203.0.113.10", BASE_TIME + timedelta(seconds=offset))
    assert blocked.allowed is False
    assert (await check_download_rate("203.0.113.11", BASE_TIME + timedelta(seconds=30))).allowed
    await engine.dispose()


def test_ipv6_normalization():
    assert normalize_ip("2001:0db8:0:0:0:0:0:1") == "2001:db8::1"
    assert hash_ip("2001:0db8:0:0:0:0:0:1") == hash_ip("2001:db8::1")
    assert normalize_ip("::ffff:192.0.2.10") == "192.0.2.10"


async def test_concurrent_four_requests_only_three_pass(tmp_path, monkeypatch):
    engine, _ = await rate_store(tmp_path, monkeypatch)
    results = await asyncio.gather(*(check_download_rate("203.0.113.10", BASE_TIME) for _ in range(4)))
    assert sum(item.allowed for item in results) == 3
    assert sum(not item.allowed for item in results) == 1
    await engine.dispose()


async def test_api_restart_keeps_rate_limit_state(tmp_path, monkeypatch):
    engine, _ = await rate_store(tmp_path, monkeypatch)
    for offset in (0, 10, 20, 30):
        blocked = await check_download_rate("203.0.113.10", BASE_TIME + timedelta(seconds=offset))
    await engine.dispose()

    restarted_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'rate.db'}")
    restarted_factory = async_sessionmaker(restarted_engine, expire_on_commit=False)
    monkeypatch.setattr(download_rate_limit, "StateSession", restarted_factory)
    after_restart = await check_download_rate("203.0.113.10", BASE_TIME + timedelta(seconds=35))
    assert after_restart.allowed is False
    assert after_restart.blocked_until == blocked.blocked_until
    assert after_restart.retry_after == 55
    await restarted_engine.dispose()


def test_untrusted_x_forwarded_for_not_accepted(monkeypatch):
    monkeypatch.setattr(download_rate_limit.settings, "trusted_proxy_cidrs", "127.0.0.1/32,172.16.0.0/12")
    assert get_effective_client_ip(request_from("198.51.100.20", "203.0.113.99")) == "198.51.100.20"


def test_trusted_proxy_chain_uses_first_untrusted_hop(monkeypatch):
    monkeypatch.setattr(download_rate_limit.settings, "trusted_proxy_cidrs", "127.0.0.1/32,172.16.0.0/12")
    request = request_from("172.20.0.5", "192.0.2.250, 198.51.100.20, 172.19.0.8")
    assert get_effective_client_ip(request) == "198.51.100.20"


async def test_rate_limit_runs_before_alist(monkeypatch):
    class FakeSession:
        def __init__(self, resource=None):
            self.resource = resource

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def get(self, model, _):
            return self.resource if model is Resource else None

    monkeypatch.setattr(main, "IndexSession", lambda: FakeSession(SimpleNamespace(status="active")))
    monkeypatch.setattr(main, "StateSession", lambda: FakeSession())

    async def denied(_):
        return DownloadRateDecision(
            False,
            retry_after=43,
            blocked_until=BASE_TIME + timedelta(seconds=43),
            ip_key="a" * 64,
        )

    async def no_event(*_args, **_kwargs):
        return None

    async def must_not_call(*_args, **_kwargs):
        raise AssertionError("rate-limited request reached AList")

    monkeypatch.setattr(main, "check_download_rate", denied)
    monkeypatch.setattr(main, "_download_event", no_event)
    monkeypatch.setattr(main, "resolve_download_entry", must_not_call)
    response = await main.download("r_1234567890", request_from("198.51.100.20"))
    assert response.status_code == 429
    assert response.headers["retry-after"] == "43"
    assert json.loads(response.body)["code"] == "DOWNLOAD_RATE_LIMITED"


async def test_download_route_first_three_302_fourth_429(tmp_path, monkeypatch):
    engine, _ = await rate_store(tmp_path, monkeypatch)

    class FakeSession:
        def __init__(self, resource=None):
            self.resource = resource

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def get(self, model, _):
            return self.resource if model is Resource else None

    monkeypatch.setattr(main, "IndexSession", lambda: FakeSession(SimpleNamespace(status="active")))
    monkeypatch.setattr(main, "StateSession", lambda: FakeSession())

    async def no_event(*_args, **_kwargs):
        return None

    async def resolved(*_args, **_kwargs):
        return SimpleNamespace(url="https://alist.example/d/file.zip")

    monkeypatch.setattr(main, "_download_event", no_event)
    monkeypatch.setattr(main, "resolve_download_entry", resolved)
    request = request_from("198.51.100.20")
    responses = [await main.download("r_1234567890", request) for _ in range(4)]
    assert [response.status_code for response in responses] == [302, 302, 302, 429]
    assert responses[-1].headers["retry-after"] == "60"
    await engine.dispose()
