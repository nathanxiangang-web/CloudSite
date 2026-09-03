"""StorageProvider 最小接口。

Provider 是对“Storage 能做什么”的抽象，不复制一套 AListClient。
Sync / Download / Preview 通过本接口访问上游，再由具体 Adapter 委托给
底层 HTTP Client。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .capabilities import ProviderCapabilities


@runtime_checkable
class StorageProvider(Protocol):
    @property
    def adapter_version(self) -> str: ...

    def capabilities(self) -> ProviderCapabilities: ...

    async def list_path(self, path: str, refresh: bool = False, strict: bool = False) -> list[dict[str, Any]]: ...

    async def get_download_entry(self, path: str) -> Any: ...

    async def get_preview_entry(self, path: str) -> Any: ...

    async def get_metadata(self, path: str) -> dict[str, Any]: ...
