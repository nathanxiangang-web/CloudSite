"""R10 PR01: DeltaCapableProvider Protocol tests (V2 doc section 27).

Verifies that the DeltaCapableProvider protocol correctly identifies
providers that implement bootstrap_cursor and fetch_changes, and
excludes those that don't.
"""
import asyncio

import pytest

from cloudsite.modules.providers.domain.capabilities import (
    CapabilityState,
    ProviderCapabilities,
)
from cloudsite.modules.providers.domain.delta import ProviderChange
from cloudsite.modules.providers.domain.provider import (
    DeltaCapableProvider,
    StorageProvider,
)
from cloudsite.modules.providers.infrastructure.testing import (
    FakeDeltaProvider,
)


class _NonDeltaProvider:
    """A provider that does NOT implement delta methods."""

    adapter_version = "non-delta@1"

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities()

    async def list_path(self, path, refresh=False, strict=False):
        return []

    async def get_download_entry(self, path):
        return None

    async def get_preview_entry(self, path):
        return None

    async def get_metadata(self, path):
        return {}

    async def stat(self, path):
        return {}

    async def identity(self, path):
        return {}


class _FullDeltaProvider:
    """A provider that implements delta methods."""

    adapter_version = "delta@1"

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_delta=CapabilityState.YES,
            supports_change_cursor=CapabilityState.YES,
        )

    async def list_path(self, path, refresh=False, strict=False):
        return []

    async def get_download_entry(self, path):
        return None

    async def get_preview_entry(self, path):
        return None

    async def get_metadata(self, path):
        return {}

    async def stat(self, path):
        return {}

    async def identity(self, path):
        return {}

    async def bootstrap_cursor(self) -> str:
        return "initial-cursor"

    async def fetch_changes(self, cursor: str | None) -> tuple[list[ProviderChange], str]:
        return [], "next-cursor"


class TestDeltaCapableProviderProtocol:
    def test_non_delta_provider_is_storage_provider(self):
        provider = _NonDeltaProvider()
        assert isinstance(provider, StorageProvider)

    def test_non_delta_provider_is_not_delta_capable(self):
        provider = _NonDeltaProvider()
        assert not isinstance(provider, DeltaCapableProvider)

    def test_full_delta_provider_is_storage_provider(self):
        provider = _FullDeltaProvider()
        assert isinstance(provider, StorageProvider)

    def test_full_delta_provider_is_delta_capable(self):
        provider = _FullDeltaProvider()
        assert isinstance(provider, DeltaCapableProvider)



class TestDeltaProviderMethods:
    def test_bootstrap_cursor_returns_str(self):
        provider = _FullDeltaProvider()
        result = asyncio.run(provider.bootstrap_cursor())
        assert isinstance(result, str)
        assert result == "initial-cursor"

    def test_fetch_changes_returns_changes_and_cursor(self):
        provider = _FullDeltaProvider()
        changes, next_cursor = asyncio.run(provider.fetch_changes(None))
        assert isinstance(changes, list)
        assert isinstance(next_cursor, str)
        assert next_cursor == "next-cursor"

    def test_fake_delta_provider_bootstrap(self):
        provider = FakeDeltaProvider(cursor="abc")
        result = asyncio.run(provider.bootstrap_cursor())
        assert result == "abc"

    def test_fake_delta_provider_fetch_changes_empty(self):
        provider = FakeDeltaProvider()
        changes, next_cursor = asyncio.run(provider.fetch_changes(None))
        assert changes == []
        assert next_cursor == "0"

    def test_fake_delta_provider_fetch_changes_with_emits(self):
        provider = (
            FakeDeltaProvider()
            .emit("create", path="/a.txt")
            .emit("delete", path="/b.txt")
        )
        changes, next_cursor = asyncio.run(provider.fetch_changes("0"))
        assert len(changes) == 2
        assert changes[0].change_type == "create"
        assert changes[0].path == "/a.txt"
        assert changes[1].change_type == "delete"
        assert changes[1].path == "/b.txt"
        assert next_cursor == "2"


class TestCapabilitiesWithDelta:
    def test_delta_capabilities_declared(self):
        caps = ProviderCapabilities(
            supports_delta=CapabilityState.YES,
            supports_change_cursor=CapabilityState.YES,
        )
        assert caps.supports_delta is CapabilityState.YES
        assert caps.supports_change_cursor is CapabilityState.YES

    def test_default_capabilities_no_delta(self):
        caps = ProviderCapabilities()
        assert caps.supports_delta is CapabilityState.NO
        assert caps.supports_change_cursor is CapabilityState.NO

    def test_capabilities_json_roundtrip_with_delta(self):
        caps = ProviderCapabilities(
            supports_delta=CapabilityState.YES,
            supports_change_cursor=CapabilityState.YES,
        )
        raw = caps.to_json()
        restored = ProviderCapabilities.from_json(raw)
        assert restored.supports_delta is CapabilityState.YES
        assert restored.supports_change_cursor is CapabilityState.YES