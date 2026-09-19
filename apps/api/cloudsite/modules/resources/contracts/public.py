from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass(slots=True)
class ResourceInventoryRecord:
    """Persistence-neutral Folder/Resource inventory record."""

    resource_id: str
    category_id: str
    provider_id: str
    path: str
    name: str
    size: int | None = None
    modified_at: datetime | None = None
    content_hash: str | None = None
    is_dir: bool = False
    parent_id: str | None = None
    content_type: str | None = None
    root_mapping_id: int | None = None
    depth: int = 0
    extension: str = ""
    mime_type: str = ""
    thumbnail: str = ""
    indexed_at: datetime | None = None


@runtime_checkable
class ResourceInventoryPort(Protocol):
    """Authoritative persistence boundary for Folder/Resource inventory state."""

    async def list_indexed(
        self,
        *,
        category_id: str,
        provider_id: str,
    ) -> list[ResourceInventoryRecord]: ...

    async def upsert(self, records: list[ResourceInventoryRecord]) -> int: ...

    async def remove(self, resource_ids: list[str]) -> int: ...

    async def touch_unchanged(self, resource_ids: list[str]) -> int: ...

    async def cascade_descendant_paths(
        self,
        old_path_prefix: str,
        new_path_prefix: str,
    ) -> dict[str, int]: ...


__all__ = ["ResourceInventoryPort", "ResourceInventoryRecord"]
