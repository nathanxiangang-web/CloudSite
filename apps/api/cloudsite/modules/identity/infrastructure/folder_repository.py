"""SQLAlchemy adapter for folder identity persistence.

The adapter intentionally exposes no commit operation: folder resolution has
historically been part of a caller-owned transaction and must remain so.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..application.ports import FolderIdentityRepository
from ..domain.records import FolderIdentityHistoryRecord, FolderIdentityRecord
from .models import FolderIdentity, FolderIdentityHistory


class SqlAlchemyFolderIdentityRepository(FolderIdentityRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._entities: dict[str, FolderIdentity] = {}

    @staticmethod
    def _to_record(entity: FolderIdentity) -> FolderIdentityRecord:
        return FolderIdentityRecord(
            folder_id=entity.folder_id,
            current_path=entity.current_path,
            root_mapping_id=entity.root_mapping_id,
            status=entity.status,
            first_seen_at=entity.first_seen_at,
            last_seen_at=entity.last_seen_at,
            last_name=entity.last_name,
            identity_fingerprint=entity.identity_fingerprint,
            fingerprint_version=entity.fingerprint_version,
            created_from=entity.created_from,
            updated_at=entity.updated_at,
        )

    @staticmethod
    def _apply(entity: FolderIdentity, record: FolderIdentityRecord) -> None:
        entity.current_path = record.current_path
        entity.root_mapping_id = record.root_mapping_id
        entity.status = record.status
        entity.first_seen_at = record.first_seen_at
        entity.last_seen_at = record.last_seen_at
        entity.last_name = record.last_name
        entity.identity_fingerprint = record.identity_fingerprint
        entity.fingerprint_version = record.fingerprint_version
        entity.created_from = record.created_from
        entity.updated_at = record.updated_at

    async def list_active_candidates(self) -> list[FolderIdentityRecord]:
        entities = list(
            (
                await self._session.scalars(
                    select(FolderIdentity).where(
                        FolderIdentity.status.in_(("active", "suspected_missing"))
                    )
                )
            ).all()
        )
        for entity in entities:
            self._entities[entity.folder_id] = entity
        return [self._to_record(entity) for entity in entities]

    async def add(self, record: FolderIdentityRecord) -> None:
        entity = FolderIdentity(
            folder_id=record.folder_id,
            current_path=record.current_path,
            root_mapping_id=record.root_mapping_id,
            status=record.status,
            first_seen_at=record.first_seen_at,
            last_seen_at=record.last_seen_at,
            last_name=record.last_name,
            identity_fingerprint=record.identity_fingerprint,
            fingerprint_version=record.fingerprint_version,
            created_from=record.created_from,
            updated_at=record.updated_at,
        )
        self._session.add(entity)
        self._entities[record.folder_id] = entity

    async def save(self, record: FolderIdentityRecord) -> None:
        entity = self._entities.get(record.folder_id)
        if entity is None:
            entity = await self._session.get(FolderIdentity, record.folder_id)
            if entity is None:
                raise RuntimeError(
                    f"Identity repository cannot save unknown folder: {record.folder_id}"
                )
            self._entities[record.folder_id] = entity
        self._apply(entity, record)

    async def add_history(self, record: FolderIdentityHistoryRecord) -> None:
        self._session.add(
            FolderIdentityHistory(
                folder_id=record.folder_id,
                path=record.path,
                event_type=record.event_type,
                from_path=record.from_path,
                to_path=record.to_path,
                cycle_id=record.cycle_id,
            )
        )


__all__ = ["SqlAlchemyFolderIdentityRepository"]
