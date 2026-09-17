from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import Index, String, Text, delete, select, update
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON
from sqlalchemy.ext.asyncio import AsyncSession

from cloudsite.platform.db.base import StateBase


class ResourceSkeletonORM(StateBase):
    """ORM mapping for the resource_skeletons indexing table."""

    __tablename__ = 'resource_skeletons'

    resource_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    category_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    provider_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    size: Mapped[int | None] = mapped_column(nullable=True)
    modified_at: Mapped[datetime | None] = mapped_column(nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    meta: Mapped[dict[str, Any] | None] = mapped_column('metadata', JSON, nullable=True)
    indexed_at: Mapped[datetime] = mapped_column(nullable=False)

    __table_args__ = (
        Index('ix_resource_skeletons_cat_prov', 'category_id', 'provider_id'),
    )


@dataclass(slots=True)
class IndexedEntry:
    """A resource entry as currently stored in the indexing tables."""
    resource_id: str
    category_id: str
    provider_id: str
    path: str
    name: str
    size: int | None = None
    modified_at: datetime | None = None
    content_hash: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    indexed_at: datetime | None = None


@runtime_checkable
class IndexingStore(Protocol):
    """Data-access abstraction for indexing state.

    The ReconcileService depends on this protocol so that unit tests can
    inject an in-memory fake without touching the database.
    """

    async def list_indexed(self, *, category_id: str, provider_id: str) -> list[IndexedEntry]: ...
    async def upsert(self, entries: list[IndexedEntry]) -> int: ...
    async def remove(self, resource_ids: list[str]) -> int: ...
    async def touch_unchanged(self, resource_ids: list[str]) -> int: ...


class IndexingRepository:
    """DB-backed indexing store following platform/db repository patterns."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_indexed(self, *, category_id: str, provider_id: str) -> list[IndexedEntry]:
        stmt = select(ResourceSkeletonORM).where(
            ResourceSkeletonORM.category_id == category_id,
            ResourceSkeletonORM.provider_id == provider_id,
        )
        result = await self._session.execute(stmt)
        return [self._orm_to_entry(r) for r in result.scalars().all()]

    async def upsert(self, entries: list[IndexedEntry]) -> int:
        if not entries:
            return 0
        now = datetime.now(timezone.utc)
        count = 0
        for entry in entries:
            existing = await self._session.get(ResourceSkeletonORM, entry.resource_id)
            if existing is None:
                self._session.add(self._entry_to_orm(entry, now))
            else:
                self._apply_update(existing, entry, now)
            count += 1
        await self._session.flush()
        return count

    async def remove(self, resource_ids: list[str]) -> int:
        if not resource_ids:
            return 0
        stmt = delete(ResourceSkeletonORM).where(
            ResourceSkeletonORM.resource_id.in_(resource_ids)
        )
        result = await self._session.execute(stmt)
        return result.rowcount or 0

    async def touch_unchanged(self, resource_ids: list[str]) -> int:
        if not resource_ids:
            return 0
        now = datetime.now(timezone.utc)
        stmt = (
            update(ResourceSkeletonORM)
            .where(ResourceSkeletonORM.resource_id.in_(resource_ids))
            .values(indexed_at=now)
        )
        result = await self._session.execute(stmt)
        return result.rowcount or 0

    @staticmethod
    def _orm_to_entry(r: ResourceSkeletonORM) -> IndexedEntry:
        return IndexedEntry(
            resource_id=r.resource_id,
            category_id=r.category_id,
            provider_id=r.provider_id,
            path=r.path,
            name=r.name,
            size=r.size,
            modified_at=r.modified_at,
            content_hash=r.content_hash,
            metadata=r.meta or {},
            indexed_at=r.indexed_at,
        )

    @staticmethod
    def _entry_to_orm(entry: IndexedEntry, now: datetime) -> ResourceSkeletonORM:
        return ResourceSkeletonORM(
            resource_id=entry.resource_id,
            category_id=entry.category_id,
            provider_id=entry.provider_id,
            path=entry.path,
            name=entry.name,
            size=entry.size,
            modified_at=entry.modified_at,
            content_hash=entry.content_hash,
            meta=entry.metadata or None,
            indexed_at=entry.indexed_at or now,
        )

    @staticmethod
    def _apply_update(orm: ResourceSkeletonORM, entry: IndexedEntry, now: datetime) -> None:
        orm.category_id = entry.category_id
        orm.provider_id = entry.provider_id
        orm.path = entry.path
        orm.name = entry.name
        orm.size = entry.size
        orm.modified_at = entry.modified_at
        orm.content_hash = entry.content_hash
        orm.meta = entry.metadata or None
        orm.indexed_at = entry.indexed_at or now


__all__ = [
    'ResourceSkeletonORM',
    'IndexedEntry',
    'IndexingStore',
    'IndexingRepository',
]