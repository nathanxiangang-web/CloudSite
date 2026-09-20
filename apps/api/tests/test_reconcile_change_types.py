"""R3 PR03: reconcile change-type enhancement (V2 doc section 21).

Verifies that ReconcileService distinguishes all 7 change types:
added / changed / renamed / moved / removed / unchanged / conflict.

Rename/move detection is identity-based: an incoming entry that is not
matched by resource_id but shares a content identity (content_hash) with
an unmatched existing entry is classified as RENAMED (same parent dir) or
MOVED (different parent dir) instead of REMOVED + ADDED. Ambiguous
identity collisions (multiple candidates on either side) are reported as
CONFLICT and are never silently resolved.
"""
from __future__ import annotations

from datetime import datetime, timezone

from cloudsite.modules.indexing.application.reconcile import (
    ReconcileService,
    WriteSummary,
)
from cloudsite.modules.indexing.domain.change import ChangeType
from cloudsite.modules.indexing.domain.snapshot import CategorySnapshot, SnapshotEntry
from cloudsite.modules.indexing.infrastructure.repository import IndexedEntry


_NOW = datetime(2026, 9, 20, tzinfo=timezone.utc)
_CAT = "cat-1"
_PROV = "prov-1"


class _Store:
    """In-memory IndexingStore recording all write calls."""

    def __init__(self, existing: list[IndexedEntry] | None = None) -> None:
        self._data: dict[str, IndexedEntry] = {
            e.resource_id: e for e in (existing or [])
        }
        self.upsert_calls: list[list[IndexedEntry]] = []
        self.remove_calls: list[list[str]] = []
        self.touch_calls: list[list[str]] = []

    async def list_indexed(self, *, category_id: str, provider_id: str) -> list[IndexedEntry]:
        return [
            e for e in self._data.values()
            if e.category_id == category_id and e.provider_id == provider_id
        ]

    async def upsert(self, entries: list[IndexedEntry]) -> int:
        self.upsert_calls.append(list(entries))
        for e in entries:
            self._data[e.resource_id] = e
        return len(entries)

    async def remove(self, resource_ids: list[str]) -> int:
        self.remove_calls.append(list(resource_ids))
        count = 0
        for rid in resource_ids:
            if rid in self._data:
                del self._data[rid]
                count += 1
        return count

    async def touch_unchanged(self, resource_ids: list[str]) -> int:
        self.touch_calls.append(list(resource_ids))
        return len(resource_ids)


def _snap(
    rid: str,
    path: str,
    *,
    content_hash: str | None = "h1",
    size: int = 100,
    name: str | None = None,
    root_mapping_id: int = 0,
) -> SnapshotEntry:
    return SnapshotEntry(
        resource_id=rid,
        path=path,
        name=name or path.rsplit("/", 1)[-1],
        size=size,
        modified_at=_NOW,
        content_hash=content_hash,
        metadata={"is_dir": False, "root_mapping_id": root_mapping_id},
    )


def _indexed(
    rid: str,
    path: str,
    *,
    content_hash: str | None = "h1",
    size: int = 100,
    name: str | None = None,
    root_mapping_id: int = 0,
) -> IndexedEntry:
    return IndexedEntry(
        resource_id=rid,
        category_id=_CAT,
        provider_id=_PROV,
        path=path,
        name=name or path.rsplit("/", 1)[-1],
        size=size,
        modified_at=_NOW,
        content_hash=content_hash,
        metadata={"is_dir": False, "root_mapping_id": root_mapping_id},
        indexed_at=_NOW,
    )


def _types(result) -> set[ChangeType]:
    return {c.change_type for c in result.changes}


# =====================================================================
# ADDED
# =====================================================================

async def test_added_detected() -> None:
    store = _Store()
    service = ReconcileService(store)
    snapshot = CategorySnapshot(
        category_id=_CAT, provider_id=_PROV,
        entries=[_snap("r-new", "/dir/new.zip")],
        pagination_complete=True,
    )
    result = await service.reconcile(snapshot)
    assert _types(result) == {ChangeType.ADDED}
    assert result.writes.added == 1
    assert result.change_type_counts[ChangeType.ADDED] == 1


# =====================================================================
# CHANGED
# =====================================================================

async def test_changed_detected() -> None:
    existing = [_indexed("r-1", "/dir/file.zip", content_hash="h-old", size=10)]
    store = _Store(existing=existing)
    service = ReconcileService(store)
    snapshot = CategorySnapshot(
        category_id=_CAT, provider_id=_PROV,
        entries=[_snap("r-1", "/dir/file.zip", content_hash="h-new", size=20)],
        pagination_complete=True,
    )
    result = await service.reconcile(snapshot)
    assert _types(result) == {ChangeType.CHANGED}
    assert result.writes.changed == 1
    assert result.change_type_counts[ChangeType.CHANGED] == 1


# =====================================================================
# RENAMED (same parent dir, different name, same content_hash)
# =====================================================================

async def test_renamed_detected() -> None:
    existing = [_indexed("r-1", "/dir/old-name.zip", content_hash="h-same")]
    store = _Store(existing=existing)
    service = ReconcileService(store)
    snapshot = CategorySnapshot(
        category_id=_CAT, provider_id=_PROV,
        entries=[_snap("r-2", "/dir/new-name.zip", content_hash="h-same")],
        pagination_complete=True,
    )
    result = await service.reconcile(snapshot)
    types = _types(result)
    assert ChangeType.RENAMED in types
    assert ChangeType.REMOVED not in types
    assert ChangeType.ADDED not in types
    assert result.change_type_counts[ChangeType.RENAMED] == 1


async def test_renamed_preserves_resource_id() -> None:
    existing = [_indexed("legacy-id", "/dir/old.zip", content_hash="h-same")]
    store = _Store(existing=existing)
    service = ReconcileService(store)
    snapshot = CategorySnapshot(
        category_id=_CAT, provider_id=_PROV,
        entries=[_snap("new-id", "/dir/renamed.zip", content_hash="h-same")],
        pagination_complete=True,
    )
    result = await service.reconcile(snapshot)
    renamed = [c for c in result.changes if c.change_type is ChangeType.RENAMED]
    assert len(renamed) == 1
    assert renamed[0].resource_id == "legacy-id"
    assert store.upsert_calls
    assert store.upsert_calls[0][0].resource_id == "legacy-id"


# =====================================================================
# MOVED (different parent dir, same content_hash)
# =====================================================================

async def test_moved_detected() -> None:
    existing = [_indexed("r-1", "/old-dir/file.zip", content_hash="h-same")]
    store = _Store(existing=existing)
    service = ReconcileService(store)
    snapshot = CategorySnapshot(
        category_id=_CAT, provider_id=_PROV,
        entries=[_snap("r-2", "/new-dir/file.zip", content_hash="h-same")],
        pagination_complete=True,
    )
    result = await service.reconcile(snapshot)
    types = _types(result)
    assert ChangeType.MOVED in types
    assert ChangeType.REMOVED not in types
    assert ChangeType.ADDED not in types
    assert result.change_type_counts[ChangeType.MOVED] == 1


async def test_moved_preserves_resource_id() -> None:
    existing = [_indexed("legacy-id", "/old-dir/file.zip", content_hash="h-same")]
    store = _Store(existing=existing)
    service = ReconcileService(store)
    snapshot = CategorySnapshot(
        category_id=_CAT, provider_id=_PROV,
        entries=[_snap("new-id", "/new-dir/file.zip", content_hash="h-same")],
        pagination_complete=True,
    )
    result = await service.reconcile(snapshot)
    moved = [c for c in result.changes if c.change_type is ChangeType.MOVED]
    assert len(moved) == 1
    assert moved[0].resource_id == "legacy-id"
    assert store.upsert_calls
    assert store.upsert_calls[0][0].resource_id == "legacy-id"


# Same content hash across roots must never preserve identity.
async def test_cross_root_same_hash_is_not_treated_as_move() -> None:
    existing = [
        _indexed(
            "legacy-id",
            "/root-a/file.zip",
            content_hash="h-same",
            root_mapping_id=1,
        )
    ]
    store = _Store(existing=existing)
    service = ReconcileService(store)
    snapshot = CategorySnapshot(
        category_id=_CAT,
        provider_id=_PROV,
        entries=[
            _snap(
                "new-id",
                "/root-b/file.zip",
                content_hash="h-same",
                root_mapping_id=2,
            )
        ],
        pagination_complete=True,
    )

    result = await service.reconcile(snapshot)
    types = _types(result)

    assert ChangeType.MOVED not in types
    assert ChangeType.RENAMED not in types
    assert ChangeType.ADDED in types
    assert ChangeType.REMOVED in types
    assert store.upsert_calls[0][0].resource_id == "new-id"


# =====================================================================
# REMOVED
# =====================================================================

async def test_removed_detected() -> None:
    existing = [
        _indexed("r-keep", "/dir/keep.zip", content_hash="h-keep"),
        _indexed("r-gone", "/dir/gone.zip", content_hash="h-gone"),
    ]
    store = _Store(existing=existing)
    service = ReconcileService(store)
    snapshot = CategorySnapshot(
        category_id=_CAT, provider_id=_PROV,
        entries=[_snap("r-keep", "/dir/keep.zip", content_hash="h-keep")],
        pagination_complete=True,
    )
    result = await service.reconcile(snapshot)
    assert ChangeType.REMOVED in _types(result)
    assert result.writes.removed == 1
    assert result.change_type_counts[ChangeType.REMOVED] == 1


# =====================================================================
# UNCHANGED
# =====================================================================

async def test_unchanged_detected() -> None:
    existing = [_indexed("r-1", "/dir/file.zip", content_hash="h-same", size=50)]
    store = _Store(existing=existing)
    service = ReconcileService(store)
    snapshot = CategorySnapshot(
        category_id=_CAT, provider_id=_PROV,
        entries=[_snap("r-1", "/dir/file.zip", content_hash="h-same", size=50)],
        pagination_complete=True,
    )
    result = await service.reconcile(snapshot)
    assert _types(result) == {ChangeType.UNCHANGED}
    assert result.writes.unchanged == 1
    assert result.change_type_counts[ChangeType.UNCHANGED] == 1


# =====================================================================
# CONFLICT (identity collision: multiple candidates)
# =====================================================================

async def test_conflict_detected() -> None:
    # Two existing entries share the same content_hash; one incoming entry
    # with that hash cannot be unambiguously paired -> CONFLICT.
    existing = [
        _indexed("r-old-a", "/dir/a.zip", content_hash="h-collide"),
        _indexed("r-old-b", "/dir/b.zip", content_hash="h-collide"),
    ]
    store = _Store(existing=existing)
    service = ReconcileService(store)
    snapshot = CategorySnapshot(
        category_id=_CAT, provider_id=_PROV,
        entries=[_snap("r-incoming", "/dir/c.zip", content_hash="h-collide")],
        pagination_complete=True,
    )
    result = await service.reconcile(snapshot)
    assert ChangeType.CONFLICT in _types(result)
    assert result.change_type_counts[ChangeType.CONFLICT] >= 1


async def test_conflict_not_silently_resolved() -> None:
    # Conflict entries must NOT be written: no upsert for the incoming
    # conflict entry and no remove for the conflicting existing entries.
    existing = [
        _indexed("r-old-a", "/dir/a.zip", content_hash="h-collide"),
        _indexed("r-old-b", "/dir/b.zip", content_hash="h-collide"),
    ]
    store = _Store(existing=existing)
    service = ReconcileService(store)
    snapshot = CategorySnapshot(
        category_id=_CAT, provider_id=_PROV,
        entries=[_snap("r-incoming", "/dir/c.zip", content_hash="h-collide")],
        pagination_complete=True,
    )
    result = await service.reconcile(snapshot)
    conflict_ids = {
        c.resource_id for c in result.changes
        if c.change_type is ChangeType.CONFLICT
    }
    # The incoming conflicting entry must not be upserted.
    upserted_ids = {
        e.resource_id for batch in store.upsert_calls for e in batch
    }
    assert conflict_ids.isdisjoint(upserted_ids), (
        "conflict entries must not be upserted (no silent resolution)"
    )
    # The conflicting existing entries must not be removed.
    removed_ids = {rid for batch in store.remove_calls for rid in batch}
    assert conflict_ids.isdisjoint(removed_ids), (
        "conflict entries must not be removed (no silent resolution)"
    )
    assert result.writes.conflict >= 1


# =====================================================================
# change_type_counts covers all 7 types
# =====================================================================

async def test_change_type_counts() -> None:
    # Build a snapshot exercising all 7 types at once:
    #   - r-keep   : UNCHANGED (same id, same content)
    #   - r-mod    : CHANGED   (same id, different content)
    #   - r-rn     : RENAMED   (new id, same hash, same dir, different name)
    #   - r-mv     : MOVED     (new id, same hash, different dir)
    #   - r-new    : ADDED     (new id, new hash)
    #   - r-gone   : REMOVED   (existing id absent from snapshot)
    #   - h-collide: CONFLICT  (two existing share a hash, one incoming matches)
    existing = [
        _indexed("r-keep", "/d/keep.zip", content_hash="hk"),
        _indexed("r-mod", "/d/mod.zip", content_hash="hm-old"),
        _indexed("r-rn-old", "/d/rn-old.zip", content_hash="hrn"),
        _indexed("r-mv-old", "/old/mv-old.zip", content_hash="hmv"),
        _indexed("r-gone", "/d/gone.zip", content_hash="hg"),
        _indexed("r-c-a", "/d/ca.zip", content_hash="hc"),
        _indexed("r-c-b", "/d/cb.zip", content_hash="hc"),
    ]
    store = _Store(existing=existing)
    service = ReconcileService(store)
    snapshot = CategorySnapshot(
        category_id=_CAT, provider_id=_PROV,
        entries=[
            _snap("r-keep", "/d/keep.zip", content_hash="hk"),
            _snap("r-mod", "/d/mod.zip", content_hash="hm-new"),
            _snap("r-rn-new", "/d/rn-new.zip", content_hash="hrn"),
            _snap("r-mv-new", "/new/mv-new.zip", content_hash="hmv"),
            _snap("r-new", "/d/fresh.zip", content_hash="hfresh"),
            _snap("r-c-in", "/d/cc.zip", content_hash="hc"),
        ],
        pagination_complete=True,
    )
    result = await service.reconcile(snapshot)
    counts = result.change_type_counts

    # All 7 keys present.
    assert set(counts.keys()) == set(ChangeType)
    # Each expected type is represented.
    assert counts[ChangeType.ADDED] == 1
    assert counts[ChangeType.CHANGED] == 1
    assert counts[ChangeType.RENAMED] == 1
    assert counts[ChangeType.MOVED] == 1
    assert counts[ChangeType.UNCHANGED] == 1
    assert counts[ChangeType.REMOVED] == 1
    assert counts[ChangeType.CONFLICT] >= 1
    # Total change records equal sum of counts.
    assert len(result.changes) == sum(counts.values())


# =====================================================================
# WriteSummary total_writes includes renamed + moved
# =====================================================================

async def test_write_summary_total_writes_includes_rename_move() -> None:
    ws = WriteSummary(added=1, changed=1, renamed=2, moved=3, removed=1, unchanged=4)
    assert ws.total_writes == 1 + 1 + 2 + 3 + 1
