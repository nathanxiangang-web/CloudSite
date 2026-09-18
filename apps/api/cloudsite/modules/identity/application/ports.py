"""Application ports for Identity persistence and audit side effects."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from ..domain.records import (
    FolderIdentityHistoryRecord,
    FolderIdentityRecord,
    ResourceIdentityHistoryRecord,
    ResourceIdentityRecord,
)


@runtime_checkable
class ResourceIdentityRepository(Protocol):
    async def list_for_roots(
        self, root_mapping_ids: set[int | None]
    ) -> list[ResourceIdentityRecord]: ...

    async def id_exists(self, resource_id: str) -> bool: ...

    async def add(self, record: ResourceIdentityRecord) -> None: ...

    async def save(self, record: ResourceIdentityRecord) -> None: ...

    async def add_history(self, record: ResourceIdentityHistoryRecord) -> None: ...

    async def commit(self) -> None: ...


@runtime_checkable
class FolderIdentityRepository(Protocol):
    async def list_active_candidates(self) -> list[FolderIdentityRecord]: ...

    async def add(self, record: FolderIdentityRecord) -> None: ...

    async def save(self, record: FolderIdentityRecord) -> None: ...

    async def add_history(self, record: FolderIdentityHistoryRecord) -> None: ...


@runtime_checkable
class IdentityAuditSink(Protocol):
    async def record(
        self,
        *,
        level: str,
        action: str,
        message: str,
        created_at: datetime,
    ) -> None: ...


class NullIdentityAuditSink:
    async def record(
        self,
        *,
        level: str,
        action: str,
        message: str,
        created_at: datetime,
    ) -> None:
        return None


__all__ = [
    "FolderIdentityRepository",
    "IdentityAuditSink",
    "NullIdentityAuditSink",
    "ResourceIdentityRepository",
]
