from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any

from ..domain.change import ChangeRecord, ChangeType
from ..domain.snapshot import CategorySnapshot
from ..infrastructure.repository import IndexedEntry, IndexingStore


@dataclass(slots=True)
class WriteSummary:
    added: int = 0
    changed: int = 0
    removed: int = 0
    unchanged: int = 0

    @property
    def total_writes(self) -> int:
        return self.added + self.changed + self.removed


@dataclass(slots=True)
class ReconcileResult:
    changes: list[ChangeRecord] = field(default_factory=list)
    writes: WriteSummary = field(default_factory=WriteSummary)
    suppressed_removals: int = 0
    pagination_complete: bool = True

    @property
    def removal_writes_blocked(self) -> bool:
        return self.suppressed_removals > 0


_ENTRY_FIELDS: tuple[str, ...] = (
    "path",
    "name",
    "size",
    "modified_at",
    "content_hash",
)
_COMMON_METADATA_FIELDS: tuple[str, ...] = (
    "parent_id",
    "content_type",
    "root_mapping_id",
    "extension",
    "mime_type",
    "thumbnail",
)
_FOLDER_METADATA_FIELDS: tuple[str, ...] = (
    "depth",
    "child_folder_count",
    "resource_count",
)


def _entry_dict(entry: IndexedEntry) -> dict[str, Any]:
    return {field_name: getattr(entry, field_name) for field_name in _ENTRY_FIELDS}


def _snapshot_dict(entry: Any) -> dict[str, Any]:
    return {field_name: getattr(entry, field_name) for field_name in _ENTRY_FIELDS}


def _canonicalize_entries(
    existing: list[IndexedEntry],
    snapshot: CategorySnapshot,
) -> list[Any]:
    """Keep existing IDs for unchanged paths while allowing new scoped IDs."""
    existing_id_by_path = {
        entry.path: entry.resource_id
        for entry in existing
    }
    canonical_id_by_path = {
        entry.path: existing_id_by_path.get(
            entry.path,
            entry.resource_id,
        )
        for entry in snapshot.entries
    }

    result = []
    for entry in snapshot.entries:
        metadata = dict(entry.metadata or {})
        parent_path = metadata.get("parent_path")
        if parent_path:
            metadata["parent_id"] = canonical_id_by_path.get(
                str(parent_path),
                metadata.get("parent_id"),
            )
        result.append(
            replace(
                entry,
                resource_id=canonical_id_by_path[entry.path],
                metadata=metadata,
            )
        )
    return result


class ReconcileService:
    """Reconcile a CategorySnapshot against persisted indexing state.

    Invariant: when snapshot.pagination_complete is False, NO removal writes
    are issued. Entries absent from a partial snapshot may simply be
    unobserved (the provider returned a partial page or was interrupted), so
    treating them as removed would cause irreversible data loss. Removals are
    still detected and reported in changes/suppressed_removals so operators
    can see what would have been removed, but the store.remove method is
    never called.
    """

    def __init__(self, store: IndexingStore) -> None:
        self._store = store

    async def reconcile(self, snapshot: CategorySnapshot) -> ReconcileResult:
        existing = await self._store.list_indexed(
            category_id=snapshot.category_id,
            provider_id=snapshot.provider_id,
        )
        existing_by_id = {
            entry.resource_id: entry
            for entry in existing
        }
        canonical_entries = _canonicalize_entries(existing, snapshot)
        incoming_by_id = {
            entry.resource_id: entry
            for entry in canonical_entries
        }

        changes: list[ChangeRecord] = []
        added_entries: list[IndexedEntry] = []
        changed_entries: list[IndexedEntry] = []
        to_touch: list[str] = []
        removed_ids: list[str] = []

        category_id = snapshot.category_id
        provider_id = snapshot.provider_id

        for resource_id, incoming in incoming_by_id.items():
            current = existing_by_id.get(resource_id)
            if current is None:
                changes.append(
                    ChangeRecord(
                        change_type=ChangeType.ADDED,
                        resource_id=resource_id,
                        category_id=category_id,
                        provider_id=provider_id,
                        after=_snapshot_dict(incoming),
                    )
                )
                added_entries.append(
                    self._to_indexed(
                        incoming,
                        category_id,
                        provider_id,
                    )
                )
            elif self._differs(current, incoming):
                changes.append(
                    ChangeRecord(
                        change_type=ChangeType.CHANGED,
                        resource_id=resource_id,
                        category_id=category_id,
                        provider_id=provider_id,
                        before=_entry_dict(current),
                        after=_snapshot_dict(incoming),
                    )
                )
                changed_entries.append(
                    self._to_indexed(
                        incoming,
                        category_id,
                        provider_id,
                    )
                )
            else:
                changes.append(
                    ChangeRecord(
                        change_type=ChangeType.UNCHANGED,
                        resource_id=resource_id,
                        category_id=category_id,
                        provider_id=provider_id,
                    )
                )
                to_touch.append(resource_id)

        for resource_id in existing_by_id:
            if resource_id not in incoming_by_id:
                removed_ids.append(resource_id)
                changes.append(
                    ChangeRecord(
                        change_type=ChangeType.REMOVED,
                        resource_id=resource_id,
                        category_id=category_id,
                        provider_id=provider_id,
                        before=_entry_dict(existing_by_id[resource_id]),
                    )
                )

        writes = WriteSummary()
        suppressed = 0

        if added_entries or changed_entries:
            await self._store.upsert(
                added_entries + changed_entries
            )
            writes.added = len(added_entries)
            writes.changed = len(changed_entries)

        if to_touch:
            writes.unchanged = await self._store.touch_unchanged(
                to_touch
            )

        if removed_ids:
            if snapshot.pagination_complete:
                writes.removed = await self._store.remove(
                    removed_ids
                )
            else:
                suppressed = len(removed_ids)

        return ReconcileResult(
            changes=changes,
            writes=writes,
            suppressed_removals=suppressed,
            pagination_complete=snapshot.pagination_complete,
        )

    @staticmethod
    def _to_indexed(
        entry: Any,
        category_id: str,
        provider_id: str,
    ) -> IndexedEntry:
        return IndexedEntry(
            resource_id=entry.resource_id,
            category_id=category_id,
            provider_id=provider_id,
            path=entry.path,
            name=entry.name,
            size=entry.size,
            modified_at=entry.modified_at,
            content_hash=entry.content_hash,
            metadata=entry.metadata,
        )

    @staticmethod
    def _differs(
        current: IndexedEntry,
        incoming: Any,
    ) -> bool:
        for field_name in _ENTRY_FIELDS:
            if getattr(current, field_name) != getattr(
                incoming,
                field_name,
            ):
                return True

        current_metadata = current.metadata or {}
        incoming_metadata = incoming.metadata or {}
        if bool(current_metadata.get("is_dir")) != bool(
            incoming_metadata.get("is_dir")
        ):
            return True
        for field_name in _COMMON_METADATA_FIELDS:
            if current_metadata.get(
                field_name
            ) != incoming_metadata.get(field_name):
                return True
        if bool(incoming_metadata.get("is_dir")):
            for field_name in _FOLDER_METADATA_FIELDS:
                if current_metadata.get(
                    field_name
                ) != incoming_metadata.get(field_name):
                    return True
        return False


__all__ = [
    "WriteSummary",
    "ReconcileResult",
    "ReconcileService",
]
