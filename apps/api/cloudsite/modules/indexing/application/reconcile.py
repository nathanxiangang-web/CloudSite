from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any

from ..domain.change import ChangeRecord, ChangeType
from ..domain.snapshot import CategorySnapshot
from ..infrastructure.repository import IndexedEntry, IndexingStore

logger = logging.getLogger(__name__)

# When the fraction of existing entries a reconcile pass wants to remove
# exceeds this ratio, the destructive removal is suppressed as a guard
# against anomalous provider snapshots (e.g. empty AList responses that
# would otherwise wipe the whole index). See R0 PR 02 / P0-1.
SHRINK_RATIO = 0.1


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
class ScanRunSummary:
    """Aggregated scan-run state consumed by the Complete Gate (V2 §18-19).

    Carries the dir-status counts and the pagination flag so that
    ``ReconcileService.reconcile`` can decide whether removals are safe
    without taking a hard dependency on the durable-scan infrastructure.
    """

    pending_dirs: int = 0
    running_dirs: int = 0
    failed_dirs: int = 0
    pagination_complete: bool = True


@dataclass(slots=True)
class ReconcileResult:
    changes: list[ChangeRecord] = field(default_factory=list)
    writes: WriteSummary = field(default_factory=WriteSummary)
    suppressed_removals: int = 0
    pagination_complete: bool = True
    shrink_suppressed: bool = False
    degraded: bool = False
    complete_gate_reason: str | None = None

    @property
    def removal_writes_blocked(self) -> bool:
        return self.suppressed_removals > 0


def _is_snapshot_complete(scan_run: ScanRunSummary) -> bool:
    """Complete Gate predicate (V2 doc sections 18-19).

    True only when every dir is done (pending/running/failed all zero)
    AND the snapshot pagination is complete. When False the caller must
    suppress removal writes because absent entries may simply be
    unobserved rather than genuinely removed.
    """
    return (
        scan_run.pending_dirs == 0
        and scan_run.running_dirs == 0
        and scan_run.failed_dirs == 0
        and scan_run.pagination_complete is True
    )


def _complete_gate_reason(scan_run: ScanRunSummary) -> str:
    """First failing condition for the Complete Gate, for diagnostics."""
    if scan_run.pending_dirs > 0:
        return "pending_dirs"
    if scan_run.running_dirs > 0:
        return "running_dirs"
    if scan_run.failed_dirs > 0:
        return "failed_dirs"
    if not scan_run.pagination_complete:
        return "pagination_incomplete"
    return "unknown"


_ENTRY_FIELDS: tuple[str, ...] = ('path', 'name', 'size', 'modified_at', 'content_hash')
_COMMON_METADATA_FIELDS: tuple[str, ...] = (
    'parent_id', 'content_type', 'root_mapping_id',
    'extension', 'mime_type', 'thumbnail',
)
_FOLDER_METADATA_FIELDS: tuple[str, ...] = (
    'depth', 'child_folder_count', 'resource_count',
)


def _entry_dict(entry: IndexedEntry) -> dict[str, Any]:
    return {f: getattr(entry, f) for f in _ENTRY_FIELDS}


def _snapshot_dict(entry: Any) -> dict[str, Any]:
    return {f: getattr(entry, f) for f in _ENTRY_FIELDS}


def _canonicalize_entries(
    existing: list[IndexedEntry],
    snapshot: CategorySnapshot,
) -> list[Any]:
    """Keep existing IDs for unchanged paths while allowing new scoped IDs."""
    existing_id_by_key = {
        (bool((entry.metadata or {}).get("is_dir")), entry.path): entry.resource_id
        for entry in existing
    }
    canonical_id_by_key = {
        (bool((entry.metadata or {}).get("is_dir")), entry.path): existing_id_by_key.get(
            (bool((entry.metadata or {}).get("is_dir")), entry.path),
            entry.resource_id,
        )
        for entry in snapshot.entries
    }
    result = []
    for entry in snapshot.entries:
        metadata = dict(entry.metadata or {})
        entry_key = (bool(metadata.get("is_dir")), entry.path)
        parent_path = metadata.get("parent_path")
        if parent_path:
            metadata["parent_id"] = canonical_id_by_key.get(
                (True, str(parent_path)),
                metadata.get("parent_id"),
            )
        result.append(
            replace(
                entry,
                resource_id=canonical_id_by_key[entry_key],
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

    async def reconcile(
        self,
        snapshot: CategorySnapshot,
        scan_run: ScanRunSummary | None = None,
    ) -> ReconcileResult:
        existing = await self._store.list_indexed(
            category_id=snapshot.category_id,
            provider_id=snapshot.provider_id,
        )
        existing_by_id = {e.resource_id: e for e in existing}
        canonical_entries = _canonicalize_entries(existing, snapshot)
        incoming_by_id = {e.resource_id: e for e in canonical_entries}

        changes: list[ChangeRecord] = []
        added_entries: list[IndexedEntry] = []
        changed_entries: list[IndexedEntry] = []
        to_touch: list[str] = []
        removed_ids: list[str] = []

        cat = snapshot.category_id
        prov = snapshot.provider_id

        for rid, incoming in incoming_by_id.items():
            current = existing_by_id.get(rid)
            if current is None:
                changes.append(ChangeRecord(
                    change_type=ChangeType.ADDED,
                    resource_id=rid, category_id=cat, provider_id=prov,
                    after=_snapshot_dict(incoming),
                ))
                added_entries.append(self._to_indexed(incoming, cat, prov))
            elif self._differs(current, incoming):
                changes.append(ChangeRecord(
                    change_type=ChangeType.CHANGED,
                    resource_id=rid, category_id=cat, provider_id=prov,
                    before=_entry_dict(current),
                    after=_snapshot_dict(incoming),
                ))
                changed_entries.append(self._to_indexed(incoming, cat, prov))
            else:
                changes.append(ChangeRecord(
                    change_type=ChangeType.UNCHANGED,
                    resource_id=rid, category_id=cat, provider_id=prov,
                ))
                to_touch.append(rid)

        for rid in existing_by_id:
            if rid not in incoming_by_id:
                removed_ids.append(rid)
                changes.append(ChangeRecord(
                    change_type=ChangeType.REMOVED,
                    resource_id=rid, category_id=cat, provider_id=prov,
                    before=_entry_dict(existing_by_id[rid]),
                ))

        writes = WriteSummary()
        suppressed = 0
        degraded = False
        gate_reason: str | None = None

        if added_entries or changed_entries:
            await self._store.upsert(added_entries + changed_entries)
            writes.added = len(added_entries)
            writes.changed = len(changed_entries)

        if to_touch:
            writes.unchanged = await self._store.touch_unchanged(to_touch)

        # Complete Gate (V2 doc sections 18-19). When a scan_run summary is
        # supplied, removals require every dir done AND pagination complete.
        # When no scan_run is supplied, fall back to the snapshot's
        # pagination_complete flag (backward-compatible behavior).
        if scan_run is not None:
            gate_ok = _is_snapshot_complete(scan_run)
            if not gate_ok:
                degraded = True
                gate_reason = _complete_gate_reason(scan_run)
        else:
            gate_ok = snapshot.pagination_complete

        if removed_ids:
            if gate_ok:
                shrink_threshold = max(1, SHRINK_RATIO * len(existing_by_id))
                if len(removed_ids) > shrink_threshold:
                    logger.warning(
                        "anomalous shrink detected: removed=%d existing=%d, "
                        "suppressing destructive removal",
                        len(removed_ids), len(existing_by_id),
                    )
                    suppressed = len(removed_ids)
                    shrink_suppressed = True
                else:
                    writes.removed = await self._store.remove(removed_ids)
                    shrink_suppressed = False
            else:
                suppressed = len(removed_ids)
                shrink_suppressed = False
                if degraded:
                    logger.warning(
                        "complete gate failed (reason=%s): suppressing "
                        "removal of %d entries for category=%s provider=%s; "
                        "run marked degraded",
                        gate_reason, len(removed_ids), cat, prov,
                    )
        else:
            shrink_suppressed = False

        return ReconcileResult(
            changes=changes,
            writes=writes,
            suppressed_removals=suppressed,
            pagination_complete=snapshot.pagination_complete,
            shrink_suppressed=shrink_suppressed,
            degraded=degraded,
            complete_gate_reason=gate_reason,
        )

    @staticmethod
    def _to_indexed(entry: Any, category_id: str, provider_id: str) -> IndexedEntry:
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
    def _differs(current: IndexedEntry, incoming: Any) -> bool:
        for f in _ENTRY_FIELDS:
            if getattr(current, f) != getattr(incoming, f):
                return True
        current_meta = current.metadata or {}
        incoming_meta = incoming.metadata or {}
        if bool(current_meta.get("is_dir")) != bool(incoming_meta.get("is_dir")):
            return True
        for field_name in _COMMON_METADATA_FIELDS:
            if current_meta.get(field_name) != incoming_meta.get(field_name):
                return True
        if bool(incoming_meta.get("is_dir")):
            for field_name in _FOLDER_METADATA_FIELDS:
                if current_meta.get(field_name) != incoming_meta.get(field_name):
                    return True
        return False


__all__ = [
    'ReconcileResult',
    'ReconcileService',
    'ScanRunSummary',
    'WriteSummary',
]