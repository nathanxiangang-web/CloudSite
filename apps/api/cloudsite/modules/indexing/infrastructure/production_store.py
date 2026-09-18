"""Production IndexingStore writing to folders + resources tables.

Implements the IndexingStore Protocol but writes to the existing
Folder/Resource ORM tables (IndexBase, index.db) instead of the
resource_skeletons table. This lets the v2 ScanCategoryService +
ReconcileService drive the same data the frontend reads.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from cloudsite.indexer import stable_id, normalize_path
from cloudsite.models import Folder, Resource

from .repository import IndexedEntry


class ProductionIndexingStore:
    """DB-backed store writing to folders + resources tables."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_indexed(self, *, category_id: str, provider_id: str) -> list[IndexedEntry]:
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
        entries: list[IndexedEntry] = []
        for row in folders:
            entries.append(IndexedEntry(
                resource_id=row.id,
                category_id=category_id,
                provider_id=provider_id,
                path=row.path,
                name=row.name,
                size=None,
                modified_at=row.modified_at,
                content_hash=None,
                metadata={"is_dir": True, "parent_path": None},
                indexed_at=row.indexed_at,
            ))
        for row in resources:
            entries.append(IndexedEntry(
                resource_id=row.id,
                category_id=category_id,
                provider_id=provider_id,
                path=row.path,
                name=row.name,
                size=row.size,
                modified_at=row.modified_at,
                content_hash=None,
                metadata={"is_dir": False, "parent_path": None},
                indexed_at=row.indexed_at,
            ))
        return entries

    async def upsert(self, entries: list[IndexedEntry]) -> int:
        if not entries:
            return 0
        now = datetime.now(timezone.utc)
        count = 0
        for entry in entries:
            meta = entry.metadata or {}
            is_dir = meta.get("is_dir", False)
            parent_path = meta.get("parent_path")
            parent_id = stable_id("folder", parent_path) if parent_path else None
            content_type = meta.get("content_type", entry.category_id)
            root_mapping_id = meta.get("root_mapping_id")

            if is_dir:
                existing = await self._session.get(Folder, entry.resource_id)
                if existing is None:
                    existing = await self._session.scalar(
                        select(Folder).where(
                            Folder.root_mapping_id == root_mapping_id,
                            Folder.path == entry.path,
                        )
                    )
                if existing is None:
                    self._session.add(Folder(
                        id=entry.resource_id,
                        name=entry.name,
                        path=entry.path,
                        parent_id=parent_id,
                        content_type=content_type,
                        root_mapping_id=root_mapping_id,
                        depth=meta.get("depth", 0),
                        modified_at=entry.modified_at,
                        indexed_at=now,
                        status="active",
                    ))
                else:
                    existing.name = entry.name
                    existing.path = entry.path
                    existing.parent_id = parent_id
                    existing.content_type = content_type
                    existing.root_mapping_id = root_mapping_id
                    existing.modified_at = entry.modified_at
                    existing.indexed_at = now
                    existing.status = "active"
            else:
                existing = await self._session.get(Resource, entry.resource_id)
                if existing is None:
                    existing = await self._session.scalar(
                        select(Resource).where(
                            Resource.root_mapping_id == root_mapping_id,
                            Resource.path == entry.path,
                        )
                    )
                ext = meta.get("extension", "")
                mime = meta.get("mime_type", "")
                thumb = meta.get("thumbnail", "")
                if existing is None:
                    self._session.add(Resource(
                        id=entry.resource_id,
                        name=entry.name,
                        path=entry.path,
                        parent_id=parent_id,
                        content_type=content_type,
                        root_mapping_id=root_mapping_id,
                        extension=ext,
                        mime_type=mime,
                        size=entry.size or 0,
                        modified_at=entry.modified_at,
                        thumbnail=thumb,
                        indexed_at=now,
                        status="active",
                    ))
                else:
                    existing.name = entry.name
                    existing.path = entry.path
                    existing.parent_id = parent_id
                    existing.content_type = content_type
                    existing.root_mapping_id = root_mapping_id
                    existing.extension = ext
                    existing.mime_type = mime
                    existing.size = entry.size or 0
                    existing.modified_at = entry.modified_at
                    existing.thumbnail = thumb
                    existing.indexed_at = now
                    existing.status = "active"
            count += 1
        await self._session.flush()
        return count

    async def remove(self, resource_ids: list[str]) -> int:
        if not resource_ids:
            return 0
        folder_stmt = delete(Folder).where(Folder.id.in_(resource_ids))
        folder_result = await self._session.execute(folder_stmt)
        resource_stmt = delete(Resource).where(Resource.id.in_(resource_ids))
        resource_result = await self._session.execute(resource_stmt)
        return (folder_result.rowcount or 0) + (resource_result.rowcount or 0)

    async def cascade_descendant_paths(
        self,
        old_path_prefix: str,
        new_path_prefix: str,
    ) -> dict[str, int]:
        """Rewrite descendant Folder/Resource paths after a parent rename.

        Only the leading prefix is replaced. SQL LIKE wildcards in the old
        prefix are escaped so unrelated paths are never mutated.
        """
        from sqlalchemy import func

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

    async def touch_unchanged(self, resource_ids: list[str]) -> int:
        if not resource_ids:
            return 0
        now = datetime.now(timezone.utc)
        folder_stmt = (
            update(Folder)
            .where(Folder.id.in_(resource_ids))
            .values(indexed_at=now)
        )
        folder_result = await self._session.execute(folder_stmt)
        resource_stmt = (
            update(Resource)
            .where(Resource.id.in_(resource_ids))
            .values(indexed_at=now)
        )
        resource_result = await self._session.execute(resource_stmt)
        return (folder_result.rowcount or 0) + (resource_result.rowcount or 0)


__all__ = ["ProductionIndexingStore"]