from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any

from ..domain.change import ChangeRecord, ChangeType
from ..domain.identity import IdentityFingerprint, IdentityMatchingEngine
from ..domain.snapshot import CategorySnapshot
from ..infrastructure.identity_repository import IdentityRepository
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
    renamed: int = 0
    moved: int = 0
    removed: int = 0
    unchanged: int = 0
    conflict: int = 0

    @property
    def total_writes(self) -> int:
        return self.added + self.changed + self.renamed + self.moved + self.removed


@dataclass(slots=True)
class ReconcileResult:
    changes: list[ChangeRecord] = field(default_factory=list)
    writes: WriteSummary = field(default_factory=WriteSummary)
    suppressed_removals: int = 0
    pagination_complete: bool = True
    shrink_suppressed: bool = False
    conflicts: list[ChangeRecord] = field(default_factory=list)
    identity_history_updated: bool = False

    @property
    def removal_writes_blocked(self) -> bool:
        return self.suppressed_removals > 0

    @property
    def has_conflicts(self) -> bool:
        return bool(self.conflicts)

    @property
    def change_type_counts(self) -> dict[ChangeType, int]:
        """Per-type counts for all 7 change types (V2 doc section 21)."""
        counts: dict[ChangeType, int] = {ct: 0 for ct in ChangeType}
        for record in self.changes:
            counts[record.change_type] = counts.get(record.change_type, 0) + 1
        return counts


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


def _identity_key(entry: Any) -> tuple[str, int, str] | None:
    '''Content identity for rename/move detection (V2 doc section 21).

    Returns a hashable identity key when the entry has a reliable content
    identity, otherwise ''None''. Directories and entries without a content
    hash have no content identity and are skipped by rename/move detection.
    '''
    metadata = getattr(entry, 'metadata', None) or {}
    if metadata.get('is_dir'):
        return None
    content_hash = getattr(entry, 'content_hash', None)
    if not content_hash:
        return None
    return ('content', int(metadata.get('root_mapping_id', 0) or 0), content_hash)


def _parent_dir(path: str) -> str:
    '''Parent directory of a posix-style path. '/a/b.zip' -> '/a'.'''
    idx = path.rfind('/')
    if idx <= 0:
        return "/"
    return path[:idx]


def _same_directory(path1: str, path2: str) -> bool:
    return _parent_dir(path1) == _parent_dir(path2)


def _root_mapping_id(entry: Any) -> int:
    meta = getattr(entry, "metadata", None) or {}
    return int(meta.get("root_mapping_id", 0) or 0)


def _entry_fingerprint(
    engine: IdentityMatchingEngine, entry: Any,
) -> IdentityFingerprint:
    """Build a fingerprint with root_mapping_id read from entry metadata.

    SnapshotEntry stores root_mapping_id in its metadata dict rather than as a
    top-level attribute, so the identity engine's extract_fingerprint (which
    only checks attributes/dict keys) would default it to 0. This helper reads
    root_mapping_id from metadata so cross-root moves are detected correctly.
    """
    return IdentityFingerprint(
        name=str(getattr(entry, "name", "") or ""),
        size=getattr(entry, "size", None),
        modified_at=getattr(entry, "modified_at", None),
        root_mapping_id=_root_mapping_id(entry),
        path=getattr(entry, "path", None),
    )
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

    async def reconcile(self, snapshot: CategorySnapshot) -> ReconcileResult:
        existing = await self._store.list_indexed(
            category_id=snapshot.category_id,
            provider_id=snapshot.provider_id,
        )
        existing_by_id = {e.resource_id: e for e in existing}
        canonical_entries = _canonicalize_entries(existing, snapshot)
        incoming_by_id = {e.resource_id: e for e in canonical_entries}

        cat = snapshot.category_id
        prov = snapshot.provider_id

        # ------------------------------------------------------------------
        # Phase 1: exact match by resource_id (after path-based canonicalization)
        # ------------------------------------------------------------------
        matched_existing_ids: set[str] = set()
        matched_incoming_ids: set[str] = set()
        for rid in incoming_by_id:
            if rid in existing_by_id:
                matched_existing_ids.add(rid)
                matched_incoming_ids.add(rid)

        # ------------------------------------------------------------------
        # Phase 2: identity-based rename/move/conflict detection on the
        # unmatched sets (V2 doc section 21). An entry that is not matched
        # by resource_id may still be the same content at a new path.
        # ------------------------------------------------------------------
        unmatched_existing = [
            e for e in existing if e.resource_id not in matched_existing_ids
        ]
        unmatched_incoming = [
            e for e in canonical_entries if e.resource_id not in matched_incoming_ids
        ]

        existing_by_identity: dict[tuple[str, int, str], list[IndexedEntry]] = defaultdict(list)
        for entry in unmatched_existing:
            key = _identity_key(entry)
            if key is not None:
                existing_by_identity[key].append(entry)

        incoming_by_identity: dict[tuple[str, int, str], list[Any]] = defaultdict(list)
        for entry in unmatched_incoming:
            key = _identity_key(entry)
            if key is not None:
                incoming_by_identity[key].append(entry)

        # An identity with more than one candidate on either side is ambiguous
        # and is reported as CONFLICT rather than silently resolved.
        conflict_keys: set[tuple[str, int, str]] = set()
        for key, candidates in existing_by_identity.items():
            if len(candidates) > 1:
                conflict_keys.add(key)
        for key, candidates in incoming_by_identity.items():
            if len(candidates) > 1:
                conflict_keys.add(key)

        rename_pairs: dict[str, str] = {}  # incoming_id -> existing_id
        conflict_incoming_ids: set[str] = set()
        conflict_existing_ids: set[str] = set()

        shared_keys = set(existing_by_identity) & set(incoming_by_identity)
        for key in shared_keys:
            existing_list = existing_by_identity[key]
            incoming_list = incoming_by_identity[key]
            if key in conflict_keys:
                for e in existing_list:
                    conflict_existing_ids.add(e.resource_id)
                for e in incoming_list:
                    conflict_incoming_ids.add(e.resource_id)
            elif len(existing_list) == 1 and len(incoming_list) == 1:
                rename_pairs[incoming_list[0].resource_id] = existing_list[0].resource_id

        # ------------------------------------------------------------------
        # Phase 3: classify every entry into one of the 7 change types.
        # ------------------------------------------------------------------
        changes: list[ChangeRecord] = []
        added_entries: list[IndexedEntry] = []
        changed_entries: list[IndexedEntry] = []
        to_touch: list[str] = []
        removed_ids: list[str] = []

        for rid, incoming in incoming_by_id.items():
            if rid in conflict_incoming_ids:
                changes.append(ChangeRecord(
                    change_type=ChangeType.CONFLICT,
                    resource_id=rid, category_id=cat, provider_id=prov,
                    after=_snapshot_dict(incoming),
                ))
                continue

            if rid in rename_pairs:
                existing_rid = rename_pairs[rid]
                current = existing_by_id[existing_rid]
                same_parent = _parent_dir(current.path) == _parent_dir(incoming.path)
                change_type = ChangeType.RENAMED if same_parent else ChangeType.MOVED
                changes.append(ChangeRecord(
                    change_type=change_type,
                    resource_id=existing_rid, category_id=cat, provider_id=prov,
                    before=_entry_dict(current),
                    after=_snapshot_dict(incoming),
                ))
                changed_entries.append(
                    self._to_indexed(incoming, cat, prov, resource_id=existing_rid)
                )
                matched_existing_ids.add(existing_rid)
                continue

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
            if rid in matched_existing_ids:
                continue
            if rid in conflict_existing_ids:
                changes.append(ChangeRecord(
                    change_type=ChangeType.CONFLICT,
                    resource_id=rid, category_id=cat, provider_id=prov,
                    before=_entry_dict(existing_by_id[rid]),
                ))
                continue
            removed_ids.append(rid)
            changes.append(ChangeRecord(
                change_type=ChangeType.REMOVED,
                resource_id=rid, category_id=cat, provider_id=prov,
                before=_entry_dict(existing_by_id[rid]),
            ))

        writes = WriteSummary()
        suppressed = 0

        if added_entries or changed_entries:
            await self._store.upsert(added_entries + changed_entries)
        writes.added = len(added_entries)
        for record in changes:
            if record.change_type is ChangeType.CHANGED:
                writes.changed += 1
            elif record.change_type is ChangeType.RENAMED:
                writes.renamed += 1
            elif record.change_type is ChangeType.MOVED:
                writes.moved += 1

        if to_touch:
            writes.unchanged = await self._store.touch_unchanged(to_touch)

        writes.conflict = len(conflict_incoming_ids) + len(conflict_existing_ids)

        if removed_ids:
            if snapshot.pagination_complete:
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
        else:
            shrink_suppressed = False

        return ReconcileResult(
            changes=changes,
            writes=writes,
            suppressed_removals=suppressed,
            pagination_complete=snapshot.pagination_complete,
            shrink_suppressed=shrink_suppressed,
        )

    async def reconcile_with_identity(
        self,
        snapshot: CategorySnapshot,
        identity_engine: IdentityMatchingEngine | None,
        identity_repo: IdentityRepository | None = None,
    ) -> ReconcileResult:
        """Reconcile using identity matching first, then path match fallback.

        Identity match takes priority over path match: when a staging entry's
        fingerprint matches an existing identity history record, the preserved
        resource_id is reused and a path change is classified as RENAMED (same
        directory) or MOVED (different directory). Conflicts (multiple history
        records sharing the digest) are reported explicitly via ChangeType.CONFLICT
        and never silently resolved. Cross-root moves yield no_match (the digest
        encodes root_mapping_id) and fall back to new-id allocation. When
        identity_engine is None, behavior degrades to path-based reconcile.
        """
        if identity_engine is None:
            return await self.reconcile(snapshot)

        existing = await self._store.list_indexed(
            category_id=snapshot.category_id,
            provider_id=snapshot.provider_id,
        )
        existing_by_id = {e.resource_id: e for e in existing}
        existing_by_path = {
            (bool((e.metadata or {}).get("is_dir")), e.path): e
            for e in existing
        }

        changes: list[ChangeRecord] = []
        added_entries: list[IndexedEntry] = []
        changed_entries: list[IndexedEntry] = []
        to_touch: list[str] = []
        removed_ids: list[str] = []
        conflicts: list[ChangeRecord] = []
        history_to_save: list[tuple[str, IdentityFingerprint]] = []

        cat = snapshot.category_id
        prov = snapshot.provider_id

        identity_claimed_ids: set[str] = set()
        incoming_ids: set[str] = set()

        for snap_entry in snapshot.entries:
            fingerprint = _entry_fingerprint(identity_engine, snap_entry)
            history: list = []
            if identity_repo is not None:
                history = await identity_repo.find_by_fingerprint(fingerprint)
            match = identity_engine.match(fingerprint, history)

            if match.is_matched:
                preserved_id = match.resource_id
                assert preserved_id is not None
                identity_claimed_ids.add(preserved_id)
                incoming_ids.add(preserved_id)
                canonical = replace(snap_entry, resource_id=preserved_id)
                current = existing_by_id.get(preserved_id)
                if current is None:
                    changes.append(ChangeRecord(
                        change_type=ChangeType.ADDED,
                        resource_id=preserved_id, category_id=cat,
                        provider_id=prov, after=_snapshot_dict(canonical),
                    ))
                    added_entries.append(self._to_indexed(canonical, cat, prov))
                elif current.path != canonical.path:
                    change_type = (
                        ChangeType.RENAMED
                        if _same_directory(current.path, canonical.path)
                        else ChangeType.MOVED
                    )
                    changes.append(ChangeRecord(
                        change_type=change_type,
                        resource_id=preserved_id, category_id=cat,
                        provider_id=prov,
                        before=_entry_dict(current),
                        after=_snapshot_dict(canonical),
                    ))
                    changed_entries.append(self._to_indexed(canonical, cat, prov))
                elif self._differs(current, canonical):
                    changes.append(ChangeRecord(
                        change_type=ChangeType.CHANGED,
                        resource_id=preserved_id, category_id=cat,
                        provider_id=prov,
                        before=_entry_dict(current),
                        after=_snapshot_dict(canonical),
                    ))
                    changed_entries.append(self._to_indexed(canonical, cat, prov))
                else:
                    changes.append(ChangeRecord(
                        change_type=ChangeType.UNCHANGED,
                        resource_id=preserved_id, category_id=cat,
                        provider_id=prov,
                    ))
                    to_touch.append(preserved_id)
                history_to_save.append((preserved_id, fingerprint))
            elif match.is_conflict:
                conflict_record = ChangeRecord(
                    change_type=ChangeType.CONFLICT,
                    resource_id=snap_entry.resource_id,
                    category_id=cat, provider_id=prov,
                    after=_snapshot_dict(snap_entry),
                )
                changes.append(conflict_record)
                conflicts.append(conflict_record)
                incoming_ids.add(snap_entry.resource_id)
            else:
                metadata = dict(snap_entry.metadata or {})
                entry_key = (bool(metadata.get("is_dir")), snap_entry.path)
                path_existing = existing_by_path.get(entry_key)
                if (
                    path_existing is not None
                    and path_existing.resource_id not in identity_claimed_ids
                ):
                    preserved_id = path_existing.resource_id
                    identity_claimed_ids.add(preserved_id)
                    incoming_ids.add(preserved_id)
                    canonical = replace(snap_entry, resource_id=preserved_id)
                    current = existing_by_id.get(preserved_id)
                    if current is not None and self._differs(current, canonical):
                        changes.append(ChangeRecord(
                            change_type=ChangeType.CHANGED,
                            resource_id=preserved_id, category_id=cat,
                            provider_id=prov,
                            before=_entry_dict(current),
                            after=_snapshot_dict(canonical),
                        ))
                        changed_entries.append(self._to_indexed(canonical, cat, prov))
                    else:
                        changes.append(ChangeRecord(
                            change_type=ChangeType.UNCHANGED,
                            resource_id=preserved_id, category_id=cat,
                            provider_id=prov,
                        ))
                        to_touch.append(preserved_id)
                    history_to_save.append((preserved_id, fingerprint))
                else:
                    new_id = snap_entry.resource_id
                    incoming_ids.add(new_id)
                    changes.append(ChangeRecord(
                        change_type=ChangeType.ADDED,
                        resource_id=new_id, category_id=cat,
                        provider_id=prov, after=_snapshot_dict(snap_entry),
                    ))
                    added_entries.append(self._to_indexed(snap_entry, cat, prov))
                    history_to_save.append((new_id, fingerprint))

        for rid in existing_by_id:
            if rid not in incoming_ids:
                removed_ids.append(rid)
                changes.append(ChangeRecord(
                    change_type=ChangeType.REMOVED,
                    resource_id=rid, category_id=cat, provider_id=prov,
                    before=_entry_dict(existing_by_id[rid]),
                ))

        writes = WriteSummary()
        suppressed = 0
        shrink_suppressed = False

        if added_entries or changed_entries:
            await self._store.upsert(added_entries + changed_entries)
            writes.added = len(added_entries)
            writes.changed = len(changed_entries)

        if to_touch:
            writes.unchanged = await self._store.touch_unchanged(to_touch)

        if removed_ids:
            if snapshot.pagination_complete:
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
            else:
                suppressed = len(removed_ids)

        identity_history_updated = False
        if identity_repo is not None and history_to_save:
            for rid, fp in history_to_save:
                await identity_repo.save(rid, fp)
            identity_history_updated = True

        return ReconcileResult(
            changes=changes,
            writes=writes,
            suppressed_removals=suppressed,
            pagination_complete=snapshot.pagination_complete,
            shrink_suppressed=shrink_suppressed,
            conflicts=conflicts,
            identity_history_updated=identity_history_updated,
        )

    @staticmethod
    def _to_indexed(
        entry: Any,
        category_id: str,
        provider_id: str,
        *,
        resource_id: str | None = None,
    ) -> IndexedEntry:
        return IndexedEntry(
            resource_id=resource_id or entry.resource_id,
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


__all__ = ['WriteSummary', 'ReconcileResult', 'ReconcileService']