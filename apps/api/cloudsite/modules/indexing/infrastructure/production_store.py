"""Indexing adapter over the Resources inventory persistence contract."""

from __future__ import annotations

from cloudsite.modules.resources.contracts.public import (
    ResourceInventoryPort,
    ResourceInventoryRecord,
)

from .repository import IndexedEntry


class ProductionIndexingStore:
    """Adapts Indexing's reconciliation model to Resources-owned persistence."""

    def __init__(self, resources: ResourceInventoryPort) -> None:
        self._resources = resources

    async def list_indexed(
        self,
        *,
        category_id: str,
        provider_id: str,
    ) -> list[IndexedEntry]:
        records = await self._resources.list_indexed(
            category_id=category_id,
            provider_id=provider_id,
        )
        return [
            IndexedEntry(
                resource_id=record.resource_id,
                category_id=record.category_id,
                provider_id=record.provider_id,
                path=record.path,
                name=record.name,
                size=record.size,
                modified_at=record.modified_at,
                content_hash=record.content_hash,
                metadata={
                    "is_dir": record.is_dir,
                    "parent_id": record.parent_id,
                    "content_type": record.content_type,
                    "root_mapping_id": record.root_mapping_id,
                    "depth": record.depth,
                    "extension": record.extension,
                    "mime_type": record.mime_type,
                    "thumbnail": record.thumbnail,
                },
                indexed_at=record.indexed_at,
            )
            for record in records
        ]

    async def upsert(self, entries: list[IndexedEntry]) -> int:
        records = [self._to_resource_record(entry) for entry in entries]
        return await self._resources.upsert(records)

    async def remove(self, resource_ids: list[str]) -> int:
        return await self._resources.remove(resource_ids)

    async def touch_unchanged(self, resource_ids: list[str]) -> int:
        return await self._resources.touch_unchanged(resource_ids)

    async def cascade_descendant_paths(
        self,
        old_path_prefix: str,
        new_path_prefix: str,
    ) -> dict[str, int]:
        return await self._resources.cascade_descendant_paths(
            old_path_prefix,
            new_path_prefix,
        )

    @staticmethod
    def _to_resource_record(entry: IndexedEntry) -> ResourceInventoryRecord:
        meta = entry.metadata or {}
        return ResourceInventoryRecord(
            resource_id=entry.resource_id,
            category_id=entry.category_id,
            provider_id=entry.provider_id,
            path=entry.path,
            name=entry.name,
            size=entry.size,
            modified_at=entry.modified_at,
            content_hash=entry.content_hash,
            is_dir=bool(meta.get("is_dir", False)),
            parent_id=meta.get("parent_id"),
            content_type=meta.get("content_type", entry.category_id),
            root_mapping_id=meta.get("root_mapping_id"),
            depth=int(meta.get("depth", 0) or 0),
            extension=str(meta.get("extension", "") or ""),
            mime_type=str(meta.get("mime_type", "") or ""),
            thumbnail=str(meta.get("thumbnail", "") or ""),
            indexed_at=entry.indexed_at,
        )


__all__ = ["ProductionIndexingStore"]
