from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .capabilities import ProviderCapabilities
from .delta import ProviderChange


@runtime_checkable
class StorageProvider(Protocol):
    @property
    def adapter_version(self) -> str: ...

    def capabilities(self) -> ProviderCapabilities: ...

    async def list_path(self, path: str, refresh: bool = False, strict: bool = False) -> list[dict[str, Any]]: ...

    async def get_download_entry(self, path: str) -> Any: ...

    async def get_preview_entry(self, path: str) -> Any: ...

    async def get_metadata(self, path: str) -> dict[str, Any]: ...
    async def stat(self, path: str) -> dict[str, Any]: ...

    async def identity(self, path: str) -> dict[str, Any]: ...


@runtime_checkable
class DeltaCapableProvider(StorageProvider, Protocol):
    async def bootstrap_cursor(self) -> str: ...

    async def fetch_changes(self, cursor: str | None) -> tuple[list[ProviderChange], str]: ...


__all__ = ["StorageProvider", "DeltaCapableProvider"]