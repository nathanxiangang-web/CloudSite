import pytest

from cloudsite.providers import (
    CapabilityState,
    DeltaSyncStrategy,
    ProviderCapabilities,
    resolve_sync_strategy,
)
from cloudsite.providers.testing import FakeDeltaProvider


def test_generic_alist_defaults_to_rolling():
    assert resolve_sync_strategy(ProviderCapabilities()) == "rolling"


def test_delta_requires_explicit_capability():
    caps = ProviderCapabilities(
        supports_delta=CapabilityState.YES,
        supports_change_cursor=CapabilityState.YES,
    )
    assert resolve_sync_strategy(caps) == "delta"


def test_webhook_plus_delta_enables_webhook_delta():
    caps = ProviderCapabilities(
        supports_webhook=CapabilityState.YES,
        supports_delta=CapabilityState.YES,
    )
    assert resolve_sync_strategy(caps) == "webhook_delta"


def test_webhook_without_delta_does_not_enable_delta_strategy():
    assert resolve_sync_strategy(ProviderCapabilities(supports_webhook=CapabilityState.YES)) == "rolling"


def test_range_unknown_is_not_reported_as_delta():
    assert resolve_sync_strategy(ProviderCapabilities(supports_range=CapabilityState.UNKNOWN)) == "rolling"


def test_capabilities_json_roundtrip():
    caps = ProviderCapabilities(
        supports_range=CapabilityState.UNKNOWN,
        supports_delta=CapabilityState.NO,
        supports_webhook=CapabilityState.NO,
    )
    assert ProviderCapabilities.from_json(caps.to_json()) == caps


def test_capabilities_from_invalid_json_falls_back_to_defaults():
    assert ProviderCapabilities.from_json("not json") == ProviderCapabilities()
    assert ProviderCapabilities.from_json(None) == ProviderCapabilities()
    assert ProviderCapabilities.from_json('{"supports_delta": "bogus"}').supports_delta is CapabilityState.UNKNOWN


@pytest.mark.asyncio
async def test_delta_cursor_advances_after_commit():
    state = {"cursor": "0", "applied": 0}
    provider = FakeDeltaProvider().emit("created", path="/a.txt")

    async def fetch(cursor):
        return await provider.fetch_changes(cursor)

    async def apply(changes):
        state["applied"] += len(changes)
        return True

    async def load():
        return state["cursor"]

    async def save(cursor):
        state["cursor"] = cursor

    result = await DeltaSyncStrategy(fetch, apply, load, save).sync_once()
    assert result["status"] == "success"
    assert result["cursor"] == "1"
    assert state["cursor"] == "1"
    assert state["applied"] == 1


@pytest.mark.asyncio
async def test_delta_cursor_does_not_advance_on_failure():
    state = {"cursor": "0"}
    provider = FakeDeltaProvider().emit("created", path="/a.txt")

    async def fetch(cursor):
        return await provider.fetch_changes(cursor)

    async def apply(changes):
        return False

    async def load():
        return state["cursor"]

    async def save(cursor):
        state["cursor"] = cursor

    result = await DeltaSyncStrategy(fetch, apply, load, save).sync_once()
    assert result["status"] == "failed"
    assert state["cursor"] == "0"
    assert result["replayed"] is False


@pytest.mark.asyncio
async def test_delta_cursor_invalid_falls_back_to_rolling():
    state = {"cursor": "0", "invalid": False}
    provider = FakeDeltaProvider().emit("created", path="/a.txt")
    provider.invalid_after = 0

    async def fetch(cursor):
        return await provider.fetch_changes(cursor)

    async def apply(changes):
        return True

    async def load():
        return state["cursor"]

    async def save(cursor):
        state["cursor"] = cursor

    async def mark_invalid():
        state["invalid"] = True

    result = await DeltaSyncStrategy(fetch, apply, load, save, mark_invalid).sync_once()
    assert result["status"] == "cursor_invalid"
    assert result["fallback"] == "rolling"
    assert state["invalid"] is True


@pytest.mark.asyncio
async def test_delta_replay_is_idempotent_until_committed():
    provider = FakeDeltaProvider().emit("created", path="/a.txt")
    batch_a, _ = await provider.fetch_changes("0")
    batch_b, _ = await provider.fetch_changes("0")
    assert batch_a == batch_b
    assert len(batch_a) == 1

    # 提交（cursor 推进到 1）后不再返回该批。
    batch_c, _ = await provider.fetch_changes("1")
    assert batch_c == []
