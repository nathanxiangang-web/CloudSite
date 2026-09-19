"""SQLAlchemy persistence adapter for Resources inventory state."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..contracts.public import ResourceInventoryPort, ResourceInventoryRecord
from .models import Folder, Resource


class SqlAlchemyResourceInventoryRepository(ResourceInventoryPort):
    """Owns Folder/Resource reads and mutations for inventory reconciliation."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_indexed(
        self,
        *,
        category_id: str,
        provider_id: str,
    ) -> list[ResourceInventoryRecord]:
        folders = (
            await self._session.scalars(
                select(Folder).where(Folder.content_type == category_id)
            )
        ).all()
        resources = (
            await self._session.scalars(
                select(Resource).where(Resource.content_type == category_id)
            )
        ).all()

        records: list[ResourceInventoryRecord] = []
        records.extend(
            ResourceInventoryRecord(
                resource_id=row.id,
                category_id=category_id,
                provider_id=provider_id,
                path=row.path,
                name=row.name,
                size=None,
                modified_at=row.modified_at,
                content_hash=None,
                is_dir=True,
                parent_id=row.parent_id,
                content_type=row.content_type,
                root_mapping_id=row.root_mapping_id,
                depth=row.depth,
                indexed_at=row.indexed_at,
            )
            for row in folders
        )
        records.extend(
            ResourceInventoryRecord(
                resource_id=row.id,
                category_id=category_id,
                provider_id=provider_id,
                path=row.path,
                name=row.name,
                size=row.size,
                modified_at=row.modified_at,
                content_hash=None,
                is_dir=False,
                parent_id=row.parent_id,
                content_type=row.content_type,
                root_mapping_id=row.root_mapping_id,
                extension=row.extension,
                mime_type=row.mime_type,
                thumbnail=row.thumbnail,
                indexed_at=row.indexed_at,
            )
            for row in resources
        )
        return records

    async def upsert(self, records: list[ResourceInventoryRecord]) -> int:
        if not records:
            return 0

        now = datetime.now(timezone.utc)
        for record in records:
            if record.is_dir:
                existing = await self._session.get(Folder, record.resource_id)
                if existing is None:
                    existing = await self._session.scalar(
                        select(Folder).where(
                            Folder.root_mapping_id == record.root_mapping_id,
                            Folder.path == record.path,
                        )
                    )
                if existing is None:
                    self._session.add(
                        Folder(
                            id=record.resource_id,
                            name=record.name,
                            path=record.path,
                            parent_id=record.parent_id,
                            content_type=record.content_type or record.category_id,
                            root_mapping_id=record.root_mapping_id,
                            depth=record.depth,
                            modified_at=record.modified_at,
                            indexed_at=record.indexed_at or now,
                            status="active",
                        )
                    )
                else:
                    existing.name = record.name
                    existing.path = record.path
                    existing.parent_id = record.parent_id
                    existing.content_type = record.content_type or record.category_id
                    existing.root_mapping_id = record.root_mapping_id
                    existing.modified_at = record.modified_at
                    existing.indexed_at = record.indexed_at or now
                    existing.status = "active"
            else:
                existing = await self._session.get(Resource, record.resource_id)
                if existing is None:
                    existing = await self._session.scalar(
                        select(Resource).where(
                            Resource.root_mapping_id == record.root_mapping_id,
                            Resource.path == record.path,
                        )
                    )
                if existing is None:
                    self._session.add(
                        Resource(
                            id=record.resource_id,
                            name=record.name,
                            path=record.path,
                            parent_id=record.parent_id,
                            content_type=record.content_type or record.category_id,
                            root_mapping_id=record.root_mapping_id,
                            extension=record.extension,
                            mime_type=record.mime_type,
                            size=record.size or 0,
                            modified_at=record.modified_at,
                            thumbnail=record.thumbnail,
                            indexed_at=record.indexed_at or now,
                            status="active",
                        )
                    )
                else:
                    existing.name = record.name
                    existing.path = record.path
                    existing.parent_id = record.parent_id
                    existing.content_type = record.content_type or record.category_id
                    existing.root_mapping_id = record.root_mapping_id
                    existing.extension = record.extension
                    existing.mime_type = record.mime_type
                    existing.size = record.size or 0
                    existing.modified_at = record.modified_at
                    existing.thumbnail = record.thumbnail
                    existing.indexed_at = record.indexed_at or now
                    existing.status = "active"

        await self._session.flush()
        return len(records)

    async def remove(self, resource_ids: list[str]) -> int:
        if not resource_ids:
            return 0

        folder_result = await self._session.execute(
            delete(Folder).where(Folder.id.in_(resource_ids))
        )
        resource_result = await self._session.execute(
            delete(Resource).where(Resource.id.in_(resource_ids))
        )
        return (folder_result.rowcount or 0) + (resource_result.rowcount or 0)

    async def touch_unchanged(self, resource_ids: list[str]) -> int:
        if not resource_ids:
            return 0

        now = datetime.now(timezone.utc)
        folder_result = await self._session.execute(
            update(Folder)
            .where(Folder.id.in_(resource_ids))
            .values(indexed_at=now)
        )
        resource_result = await self._session.execute(
            update(Resource)
            .where(Resource.id.in_(resource_ids))
            .values(indexed_at=now)
        )
        return (folder_result.rowcount or 0) + (resource_result.rowcount or 0)

    async def cascade_descendant_paths(
        self,
        old_path_prefix: str,
        new_path_prefix: str,
    ) -> dict[str, int]:
        old_seg = old_path_prefix.rstrip("/") + "/"
        new_seg = new_path_prefix.rstrip("/") + "/"
        escaped = (
            old_seg.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        old_len = len(old_seg)

        folders_result = await self._session.execute(
            update(Folder)
            .where(Folder.path.like(escaped + "%", escape="\\"))
            .values(path=new_seg + func.substr(Folder.path, old_len + 1))
        )
        resources_result = await self._session.execute(
            update(Resource)
            .where(Resource.path.like(escaped + "%", escape="\\"))
            .values(path=new_seg + func.substr(Resource.path, old_len + 1))
        )
        return {
            "folders_updated": folders_result.rowcount or 0,
            "resources_updated": resources_result.rowcount or 0,
        }


__all__ = ["SqlAlchemyResourceInventoryRepository"]
