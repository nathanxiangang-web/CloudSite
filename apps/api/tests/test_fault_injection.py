"""Behavioural tests for the FaultInjector test harness.

These tests exercise the injector itself; they do not touch production code.
"""
from __future__ import annotations

import time
from typing import Any

import pytest

from tests.fault_injection import (
    FaultInjector,
    ProviderDisconnectError,
    ProviderRateLimitError,
)


class _FakeProvider:
    """Minimal async provider stub used only by these tests."""

    async def list_path(
        self, path: str, refresh: bool = False, strict: bool = False
    ) -> list[dict[str, Any]]:
        return [{"name": "file.txt", "path": path, "size": 100}]

    async def stat(self, path: str) -> dict[str, Any]:
        return {"name": "file.txt", "path": path, "size": 100}

    async def identity(self, path: str) -> dict[str, Any]:
        return {"path": path, "object_id": "obj-1"}

    async def get_metadata(self, path: str) -> dict[str, Any]:
        return {"path": path, "meta": "data"}


def _make_injector() -> FaultInjector:
    return FaultInjector(_FakeProvider())


async def test_fail_on_path_raises():
    injector = _make_injector().fail_on_path("/bad", RuntimeError("boom"))
    with pytest.raises(RuntimeError, match="boom"):
        await injector.list_path("/bad")
    with pytest.raises(RuntimeError, match="boom"):
        await injector.stat("/bad")


async def test_fail_after_n_requests():
    injector = _make_injector().fail_after_n_requests(2, ValueError("done"))
    assert await injector.list_path("/a") == [
        {"name": "file.txt", "path": "/a", "size": 100}
    ]
    assert await injector.list_path("/b") == [
        {"name": "file.txt", "path": "/b", "size": 100}
    ]
    with pytest.raises(ValueError, match="done"):
        await injector.list_path("/c")
    with pytest.raises(ValueError, match="done"):
        await injector.list_path("/d")


async def test_delay_on_path():
    injector = _make_injector().delay_on_path("/slow", 0.05)
    start = time.monotonic()
    await injector.list_path("/slow")
    elapsed = time.monotonic() - start
    assert elapsed >= 0.045


async def test_return_malformed():
    injector = _make_injector().return_malformed_on_path("/bad")
    result = await injector.list_path("/bad")
    assert not isinstance(result, list)
    assert result == {"__fault_injection_malformed__": True}


async def test_return_empty():
    injector = _make_injector().return_empty_on_path("/bad")
    result = await injector.list_path("/bad")
    assert result == []


async def test_rate_limit():
    injector = _make_injector().rate_limit_after_n(1)
    assert await injector.list_path("/a") == [
        {"name": "file.txt", "path": "/a", "size": 100}
    ]
    with pytest.raises(ProviderRateLimitError):
        await injector.list_path("/b")


async def test_disconnect():
    injector = _make_injector().disconnect_after_n(1)
    assert await injector.list_path("/a") == [
        {"name": "file.txt", "path": "/a", "size": 100}
    ]
    with pytest.raises(ProviderDisconnectError):
        await injector.list_path("/b")


async def test_normal_paths_unaffected():
    injector = (
        _make_injector()
        .fail_on_path("/bad", RuntimeError("boom"))
        .delay_on_path("/slow", 0.01)
        .return_malformed_on_path("/malformed")
        .return_empty_on_path("/empty")
        .rate_limit_after_n(1000)
        .disconnect_after_n(1000)
    )
    result = await injector.list_path("/good")
    assert result == [{"name": "file.txt", "path": "/good", "size": 100}]
    stat = await injector.stat("/good")
    assert stat == {"name": "file.txt", "path": "/good", "size": 100}
    ident = await injector.identity("/good")
    assert ident == {"path": "/good", "object_id": "obj-1"}
    meta = await injector.get_metadata("/good")
    assert meta == {"path": "/good", "meta": "data"}
