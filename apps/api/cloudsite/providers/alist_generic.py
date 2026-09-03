"""Generic AList Provider Adapter。

Generic AList 没有统一的 change cursor / webhook / journal，因此 delta 相关
能力一律为 NO；Range 取决于最终 Storage，保持 UNKNOWN。默认同步策略是
Rolling Full Verification。
"""

from __future__ import annotations

from typing import Any

from ..alist import AListClient, AListDownloadEntry
from .base import StorageProvider
from .capabilities import ProviderCapabilities


class GenericAListProvider:
    adapter_version = "generic_alist@1"

    def __init__(self, client: AListClient) -> None:
        self._client = client

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities()

    async def list_path(self, path: str, refresh: bool = False, strict: bool = False) -> list[dict[str, Any]]:
        return await self._client.list_path(path, refresh=refresh, strict=strict)

    async def get_download_entry(self, path: str) -> AListDownloadEntry:
        return await self._client.get_download_entry(path)

    async def get_preview_entry(self, path: str) -> AListDownloadEntry:
        return await self._client.get_preview_entry(path)

    async def get_metadata(self, path: str) -> dict[str, Any]:
        return await self._client.get_file_info(path)
