"""SQLAlchemy adapter for the Identity folder repository port."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import PurePosixPath

from sqlalchemy import delete, select
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

    async def list_active(self) -> list[FolderIdentityRecord]:
        statement = select(FolderIdentity).where(
            FolderIdentity.status.in_(("active", "suspected_missing"))
        )
        entities = list((await self._session.scalars(statement)).all())
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

    async def backfill_folder_identity(
        self,
        folder_path: str,
        resource_id: str,
        fingerprint: str | None,
        *,
        root_mapping_id: int | None = None,
        now: datetime | None = None,
    ) -> FolderIdentityRecord:
        """Backfill a FolderIdentity row for a folder observed during indexing.

        If an identity already exists at ``folder_path`` it is refreshed in
        place (fingerprint/last_seen_at updated) and returned.  Otherwise a new
        identity is created with ``created_from='backfill'`` so audit can
        distinguish backfilled rows from rows produced by the resolver.
        """
        now = now or datetime.now(timezone.utc)
        entity = await self._session.scalar(
            select(FolderIdentity).where(FolderIdentity.current_path == folder_path)
        )
        if entity is None:
            entity = FolderIdentity(
                folder_id=resource_id,
                current_path=folder_path,
                root_mapping_id=root_mapping_id,
                status="active",
                first_seen_at=now,
                last_seen_at=now,
                last_name=PurePosixPath(folder_path).name or folder_path,
                identity_fingerprint=fingerprint,
                fingerprint_version=1,
                created_from="backfill",
                updated_at=now,
            )
            self._session.add(entity)
        else:
            entity.last_seen_at = now
            entity.identity_fingerprint = fingerprint
            entity.status = "active"
            if root_mapping_id is not None:
                entity.root_mapping_id = root_mapping_id
            entity.updated_at = now
        self._entities[entity.folder_id] = entity
        return self._to_record(entity)

    async def find_folder_identity(self, folder_path: str) -> FolderIdentityRecord | None:
        """Return the folder identity currently mapped to ``folder_path``."""
        entity = await self._session.scalar(
            select(FolderIdentity).where(FolderIdentity.current_path == folder_path)
        )
        if entity is None:
            return None
        self._entities[entity.folder_id] = entity
        return self._to_record(entity)

    async def find_descendants_by_folder(
        self, folder_path: str
    ) -> list[FolderIdentityRecord]:
        """Return all folder identities whose path is nested under ``folder_path``.

        A descendant is any folder whose ``current_path`` starts with
        ``folder_path + "/"``.  The folder itself is not included.
        """
        prefix = folder_path.rstrip("/") + "/"
        statement = select(FolderIdentity).where(
            FolderIdentity.current_path.like(prefix + "%")
        )
        entities = list((await self._session.scalars(statement)).all())
        for entity in entities:
            self._entities[entity.folder_id] = entity
        return [self._to_record(entity) for entity in entities]

    async def cascade_delete_by_root(self, root_mapping_id: int) -> int:
        """Delete every folder identity owned by ``root_mapping_id``.

        Returns the number of rows removed.  History rows reference
        folder_identities with ondelete=RESTRICT, so they are removed first.
        """
        folder_ids_stmt = select(FolderIdentity.folder_id).where(
            FolderIdentity.root_mapping_id == root_mapping_id
        )
        folder_ids = list((await self._session.scalars(folder_ids_stmt)).all())
        if not folder_ids:
            return 0
        await self._session.execute(
            delete(FolderIdentityHistory).where(
                FolderIdentityHistory.folder_id.in_(folder_ids)
            )
        )
        result = await self._session.execute(
            delete(FolderIdentity).where(
                FolderIdentity.root_mapping_id == root_mapping_id
            )
        )
        for folder_id in folder_ids:
            self._entities.pop(folder_id, None)
        return int(result.rowcount or 0)


__all__ = ["SqlAlchemyFolderIdentityRepository"]
