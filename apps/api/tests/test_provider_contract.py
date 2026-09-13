"""X1 Provider 契约测试：stat/identity 能力。"""
from __future__ import annotations

from unittest.mock import AsyncMock

from cloudsite.providers.alist_generic import GenericAListProvider
from cloudsite.providers.base import StorageProvider
from cloudsite.providers.capabilities import CapabilityState


async def test_provider_implements_full_contract():
    """StorageProvider Protocol 包含 stat/identity。"""
    client = AsyncMock()
    provider = GenericAListProvider(client)
    assert isinstance(provider, StorageProvider)


async def test_stat_returns_size_and_modified():
    client = AsyncMock()
    client.get_file_info = AsyncMock(return_value={
        "name": "file.zip",
        "size": 1024,
        "modified": "2024-01-01T00:00:00Z",
        "is_dir": False,
    })
    provider = GenericAListProvider(client)
    result = await provider.stat("/path/to/file.zip")
    assert result["name"] == "file.zip"
    assert result["size"] == 1024
    assert result["is_dir"] is False


async def test_identity_returns_path_and_object_id():
    client = AsyncMock()
    client.get_file_info = AsyncMock(return_value={
        "name": "file.zip",
        "size": 1024,
        "modified": "2024-01-01T00:00:00Z",
        "object_id": "obj-123",
        "hash": "abc123",
    })
    provider = GenericAListProvider(client)
    result = await provider.identity("/path/to/file.zip")
    assert result["path"] == "/path/to/file.zip"
    assert result["object_id"] == "obj-123"
    assert result["content_hash"] == "abc123"


async def test_capabilities_default_generic_alist():
    client = AsyncMock()
    provider = GenericAListProvider(client)
    caps = provider.capabilities()
    assert caps.supports_list == CapabilityState.YES
    assert caps.supports_delta == CapabilityState.NO
    assert caps.supports_change_cursor == CapabilityState.NO


async def test_adapter_version():
    client = AsyncMock()
    provider = GenericAListProvider(client)
    assert provider.adapter_version == "generic_alist@1"