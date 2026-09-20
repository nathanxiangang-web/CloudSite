"""Provider-neutral scan source contracts.

These types let Indexing enumerate provider-backed content roots without
receiving provider ORM rows, decrypted credentials, or an AListClient.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ProviderScanPort(Protocol):
    async def list_path(
        self,
        path: str,
        refresh: bool = False,
        strict: bool = False,
    ) -> list[dict[str, Any]]: ...

    async def get_metadata(self, path: str) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class ProviderScanRoot:
    root_mapping_id: int
    content_type: str
    display_name: str
    storage_path: str


@dataclass(frozen=True, slots=True)
class ProviderScanSource:
    provider: ProviderScanPort
    roots: tuple[ProviderScanRoot, ...]


__all__ = [
    "ProviderScanPort",
    "ProviderScanRoot",
    "ProviderScanSource",
]
