"""Full Audit correctness tests (V2 doc section 75).

These tests verify that a Full Audit against a polluted formal Inventory:
  - accurately identifies every Diff kind (missing / extra / wrong path /
    stale metadata / identity conflict);
  - does NOT silently repair by default (report-only);
  - repairs diffs only when explicitly requested;
  - is idempotent when repair is applied twice;
  - reports no Diff on a clean Inventory;
  - leaves the Inventory matching the golden expected state after a sync.

The audit is built on top of the existing ``ReconcileService`` which compares
a ``CategorySnapshot`` (the expected / golden state from a provider scan) against
the persisted Inventory and produces ``ChangeRecord`` diffs.  All helpers in
this file are test-local infrastructure; no production source code is modified.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from cloudsite.modules.indexing.application.reconcile import (
    ReconcileService,
    WriteSummary,
)
from cloudsite.modules.indexing.domain.change import ChangeRecord, ChangeType
from cloudsite.modules.indexing.domain.snapshot import CategorySnapshot, SnapshotEntry
from cloudsite.modules.indexing.infrastructure.repository import IndexedEntry


# ---------------------------------------------------------------------------
# Test-local in-memory IndexingStore (records all write calls)
# ---------------------------------------------------------------------------


class _FakeIndexingStore:
    """In-memory IndexingStore that records all write calls for assertions."""

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

    def snapshot_ids(self) -> set[str]:
        return set(self._data.keys())


class _ReadOnlyIndexingStore:
    """Wraps an IndexingStore: delegates reads, suppresses all writes.

    Used to implement the default "audit-only / no silent repair" mode: the
    ReconcileService still computes the full diff (``changes``), but the
    underlying Inventory is never mutated.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.suppressed_upserts: list[list[IndexedEntry]] = []
        self.suppressed_removes: list[list[str]] = []
        self.suppressed_touches: list[list[str]] = []

    async def list_indexed(self, *, category_id: str, provider_id: str) -> list[IndexedEntry]:
        return await self._inner.list_indexed(category_id=category_id, provider_id=provider_id)

    async def upsert(self, entries: list[IndexedEntry]) -> int:
        self.suppressed_upserts.append(list(entries))
        return 0

    async def remove(self, resource_ids: list[str]) -> int:
        self.suppressed_removes.append(list(resource_ids))
        return 0

    async def touch_unchanged(self, resource_ids: list[str]) -> int:
        self.suppressed_touches.append(list(resource_ids))
        return 0


# ---------------------------------------------------------------------------
# Test-local Full Audit helper (report-only by default, explicit repair)
# ---------------------------------------------------------------------------


@dataclass
class AuditReport:
    """Result of a Full Audit pass against the Inventory."""

    missing: list[ChangeRecord] = field(default_factory=list)
    extra: list[ChangeRecord] = field(default_factory=list)
    changed: list[ChangeRecord] = field(default_factory=list)
    identity_conflicts: list[tuple[str, str, str]] = field(default_factory=list)
    writes: WriteSummary = field(default_factory=WriteSummary)
    pagination_complete: bool = True

    @property
    def clean(self) -> bool:
        return (
            not self.missing
            and not self.extra
            and not self.changed
            and not self.identity_conflicts
        )

    @property
    def total_diffs(self) -> int:
        return (
            len(self.missing)
            + len(self.extra)
            + len(self.changed)
            + len(self.identity_conflicts)
        )


def _detect_identity_conflicts(
    existing: list[IndexedEntry],
) -> list[tuple[str, str, str]]:
    """Return ``(path, id_a, id_b)`` for any path claimed by >1 resource id."""
    by_path: dict[str, list[str]] = {}
    for e in existing:
        by_path.setdefault(e.path, []).append(e.resource_id)
    conflicts: list[tuple[str, str, str]] = []
    for path, ids in by_path.items():
        if len(ids) > 1:
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    conflicts.append((path, ids[i], ids[j]))
    return conflicts


class FullAudit:
    """Full Audit over a persisted Inventory.

    ``audit`` is the default report-only mode (no writes, no silent repair).
    ``repair`` explicitly applies the diff to bring the Inventory in line with
    the expected snapshot.
    """

    def __init__(self, store: Any) -> None:
        self._store = store

    async def audit(self, snapshot: CategorySnapshot) -> AuditReport:
        existing = await self._store.list_indexed(
            category_id=snapshot.category_id,
            provider_id=snapshot.provider_id,
        )
        conflicts = _detect_identity_conflicts(existing)
        ro = _ReadOnlyIndexingStore(self._store)
        result = await ReconcileService(ro).reconcile(snapshot)
        return AuditReport(
            missing=[c for c in result.changes if c.change_type is ChangeType.ADDED],
            extra=[c for c in result.changes if c.change_type is ChangeType.REMOVED],
            changed=[c for c in result.changes if c.change_type is ChangeType.CHANGED],
            identity_conflicts=conflicts,
            writes=result.writes,
            pagination_complete=result.pagination_complete,
        )

    async def repair(self, snapshot: CategorySnapshot) -> AuditReport:
        existing = await self._store.list_indexed(
            category_id=snapshot.category_id,
            provider_id=snapshot.provider_id,
        )
        conflicts = _detect_identity_conflicts(existing)
        result = await ReconcileService(self._store).reconcile(snapshot)
        return AuditReport(
            missing=[c for c in result.changes if c.change_type is ChangeType.ADDED],
            extra=[c for c in result.changes if c.change_type is ChangeType.REMOVED],
            changed=[c for c in result.changes if c.change_type is ChangeType.CHANGED],
            identity_conflicts=conflicts,
            writes=result.writes,
            pagination_complete=result.pagination_complete,
        )


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

_CAT = "root:1"
_PROV = "generic_alist"


def _entry(
    rid: str,
    path: str,
    *,
    name: str | None = None,
    size: int | None = 100,
    content_hash: str | None = "ch-1",
    is_dir: bool = False,
    root_mapping_id: int = 1,
    content_type: str = "file",
    extension: str = "zip",
    mime_type: str = "application/zip",
) -> IndexedEntry:
    return IndexedEntry(
        resource_id=rid,
        category_id=_CAT,
        provider_id=_PROV,
        path=path,
        name=name if name is not None else path.rsplit("/", 1)[-1],
        size=size,
        content_hash=content_hash,
        metadata={
            "is_dir": is_dir,
            "parent_id": None,
            "content_type": content_type,
            "root_mapping_id": root_mapping_id,
            "extension": extension,
            "mime_type": mime_type,
            "thumbnail": "",
            "depth": 0,
            "child_folder_count": 0,
            "resource_count": 0,
        },
    )


def _snap(
    rid: str,
    path: str,
    *,
    name: str | None = None,
    size: int | None = 100,
    content_hash: str | None = "ch-1",
    is_dir: bool = False,
    root_mapping_id: int = 1,
    content_type: str = "file",
    extension: str = "zip",
    mime_type: str = "application/zip",
) -> SnapshotEntry:
    return SnapshotEntry(
        resource_id=rid,
        path=path,
        name=name if name is not None else path.rsplit("/", 1)[-1],
        size=size,
        content_hash=content_hash,
        metadata={
            "is_dir": is_dir,
            "parent_id": None,
            "content_type": content_type,
            "root_mapping_id": root_mapping_id,
            "extension": extension,
            "mime_type": mime_type,
            "thumbnail": "",
            "depth": 0,
            "child_folder_count": 0,
            "resource_count": 0,
        },
    )


def _snapshot(entries: list[SnapshotEntry], *, complete: bool = True) -> CategorySnapshot:
    return CategorySnapshot(
        category_id=_CAT,
        provider_id=_PROV,
        entries=entries,
        pagination_complete=complete,
    )


# ---------------------------------------------------------------------------
# Diff identification tests
# ---------------------------------------------------------------------------


async def test_audit_detects_missing_row():
    """Pollute Inventory by deleting a row -> audit identifies it as missing."""
    golden = [
        _snap("r1", "/a/file1.zip"),
        _snap("r2", "/a/file2.zip"),
        _snap("r3", "/a/file3.zip"),
    ]
    polluted_inventory = [
        _entry("r1", "/a/file1.zip"),
        _entry("r3", "/a/file3.zip"),
    ]
    store = _FakeIndexingStore(existing=polluted_inventory)
    audit = FullAudit(store)

    report = await audit.audit(_snapshot(golden))

    assert len(report.missing) == 1
    assert report.missing[0].resource_id == "r2"
    assert report.missing[0].change_type is ChangeType.ADDED
    assert report.total_diffs == 1


async def test_audit_detects_extra_row():
    """Pollute Inventory by adding a spurious row -> audit identifies it as extra."""
    golden = [
        _snap("r1", "/a/file1.zip"),
        _snap("r2", "/a/file2.zip"),
    ]
    polluted_inventory = [
        _entry("r1", "/a/file1.zip"),
        _entry("r2", "/a/file2.zip"),
        _entry("rx", "/a/extra.zip"),
    ]
    store = _FakeIndexingStore(existing=polluted_inventory)
    audit = FullAudit(store)

    report = await audit.audit(_snapshot(golden))

    assert len(report.extra) == 1
    assert report.extra[0].resource_id == "rx"
    assert report.extra[0].change_type is ChangeType.REMOVED
    assert report.total_diffs == 1


async def test_audit_detects_wrong_path():
    """Pollute Inventory by mutating a row's path -> audit identifies path mismatch."""
    golden = [_snap("r1", "/a/file1.zip")]
    polluted_inventory = [_entry("r1", "/a/WRONG.zip")]
    store = _FakeIndexingStore(existing=polluted_inventory)
    audit = FullAudit(store)

    report = await audit.audit(_snapshot(golden))

    assert len(report.changed) == 1
    assert report.changed[0].resource_id == "r1"
    assert report.changed[0].change_type is ChangeType.CHANGED
    assert report.changed[0].before is not None
    assert report.changed[0].after is not None
    assert report.changed[0].before["path"] == "/a/WRONG.zip"
    assert report.changed[0].after["path"] == "/a/file1.zip"
    assert report.total_diffs == 1


async def test_audit_detects_stale_metadata():
    """Pollute Inventory by mutating metadata -> audit identifies stale metadata."""
    golden = [_snap("r1", "/a/file1.zip", size=200, content_hash="ch-fresh")]
    polluted_inventory = [_entry("r1", "/a/file1.zip", size=100, content_hash="ch-stale")]
    store = _FakeIndexingStore(existing=polluted_inventory)
    audit = FullAudit(store)

    report = await audit.audit(_snapshot(golden))

    assert len(report.changed) == 1
    assert report.changed[0].resource_id == "r1"
    assert report.changed[0].change_type is ChangeType.CHANGED
    assert report.changed[0].before is not None
    assert report.changed[0].after is not None
    assert report.changed[0].before["size"] == 100
    assert report.changed[0].after["size"] == 200
    assert report.changed[0].before["content_hash"] == "ch-stale"
    assert report.changed[0].after["content_hash"] == "ch-fresh"
    assert report.total_diffs == 1


async def test_audit_detects_identity_conflict():
    """Pollute Inventory with two rows claiming the same path -> audit identifies conflict."""
    golden = [_snap("r1", "/a/file1.zip")]
    polluted_inventory = [
        _entry("r1", "/a/file1.zip"),
        _entry("r2", "/a/file1.zip", content_hash="ch-dup"),
    ]
    store = _FakeIndexingStore(existing=polluted_inventory)
    audit = FullAudit(store)

    report = await audit.audit(_snapshot(golden))

    assert len(report.identity_conflicts) >= 1
    conflict_paths = {c[0] for c in report.identity_conflicts}
    assert "/a/file1.zip" in conflict_paths
    conflict_ids = {c[1] for c in report.identity_conflicts} | {c[2] for c in report.identity_conflicts}
    assert "r1" in conflict_ids
    assert "r2" in conflict_ids


# ---------------------------------------------------------------------------
# Repair behavior tests
# ---------------------------------------------------------------------------


async def test_audit_default_no_silent_repair():
    """Default audit must NOT silently repair: it only reports diffs.

    After auditing a polluted Inventory, the Inventory state must be unchanged.
    """
    golden = [
        _snap("r1", "/a/file1.zip"),
        _snap("r2", "/a/file2.zip", content_hash="ch-r2"),
    ]
    polluted_inventory = [
        _entry("r1", "/a/file1.zip"),
        _entry("rx", "/a/extra.zip", content_hash="ch-rx"),
    ]
    store = _FakeIndexingStore(existing=polluted_inventory)
    audit = FullAudit(store)

    ids_before = store.snapshot_ids()
    report = await audit.audit(_snapshot(golden))
    ids_after = store.snapshot_ids()

    assert report.total_diffs > 0
    assert ids_before == ids_after, "audit-only mode must not mutate the Inventory"
    assert store.upsert_calls == [], "audit-only mode must not upsert"
    assert store.remove_calls == [], "audit-only mode must not remove"


async def test_audit_explicit_repair_fixes_missing():
    """Explicit repair must restore rows missing from the Inventory."""
    golden = [
        _snap("r1", "/a/file1.zip"),
        _snap("r2", "/a/file2.zip"),
    ]
    polluted_inventory = [_entry("r1", "/a/file1.zip")]
    store = _FakeIndexingStore(existing=polluted_inventory)
    audit = FullAudit(store)

    report = await audit.repair(_snapshot(golden))

    assert report.writes.added == 1
    assert "r2" in store.snapshot_ids()
    assert len(store.upsert_calls) >= 1
    remaining = await store.list_indexed(category_id=_CAT, provider_id=_PROV)
    assert {e.resource_id for e in remaining} == {"r1", "r2"}


async def test_audit_explicit_repair_fixes_extra():
    """Explicit repair must remove extra rows from the Inventory."""
    golden = [_snap("r1", "/a/file1.zip")]
    polluted_inventory = [
        _entry("r1", "/a/file1.zip"),
        _entry("rx", "/a/extra.zip"),
    ]
    store = _FakeIndexingStore(existing=polluted_inventory)
    audit = FullAudit(store)

    report = await audit.repair(_snapshot(golden))

    assert report.writes.removed == 1
    assert "rx" not in store.snapshot_ids()
    assert len(store.remove_calls) >= 1
    remaining = await store.list_indexed(category_id=_CAT, provider_id=_PROV)
    assert {e.resource_id for e in remaining} == {"r1"}


async def test_audit_repair_idempotent():
    """Two consecutive repairs: the second must report no writes / no diffs."""
    golden = [
        _snap("r1", "/a/file1.zip"),
        _snap("r2", "/a/file2.zip"),
    ]
    polluted_inventory = [_entry("r1", "/a/file1.zip")]
    store = _FakeIndexingStore(existing=polluted_inventory)
    audit = FullAudit(store)

    first = await audit.repair(_snapshot(golden))
    assert first.writes.added >= 1

    second = await audit.repair(_snapshot(golden))

    assert second.writes.added == 0
    assert second.writes.changed == 0
    assert second.writes.removed == 0
    assert second.missing == []
    assert second.extra == []
    assert second.changed == []
    assert second.identity_conflicts == []


# ---------------------------------------------------------------------------
# Integrity tests
# ---------------------------------------------------------------------------


async def test_audit_clean_inventory_no_diff():
    """A clean Inventory matching the golden snapshot must report no diffs."""
    golden = [
        _snap("r1", "/a/file1.zip"),
        _snap("r2", "/a/file2.zip"),
    ]
    clean_inventory = [
        _entry("r1", "/a/file1.zip"),
        _entry("r2", "/a/file2.zip"),
    ]
    store = _FakeIndexingStore(existing=clean_inventory)
    audit = FullAudit(store)

    report = await audit.audit(_snapshot(golden))

    assert report.clean is True
    assert report.total_diffs == 0
    assert report.missing == []
    assert report.extra == []
    assert report.changed == []
    assert report.identity_conflicts == []


async def test_audit_after_sync_matches_expected():
    """After a sync (repair from empty), audit must report clean vs golden."""
    golden = [
        _snap("r1", "/a/file1.zip"),
        _snap("r2", "/a/file2.zip"),
        _snap("r3", "/a/file3.zip"),
    ]
    store = _FakeIndexingStore(existing=[])
    audit = FullAudit(store)

    sync_report = await audit.repair(_snapshot(golden))
    assert sync_report.writes.added == 3

    post_audit = await audit.audit(_snapshot(golden))

    assert post_audit.clean is True
    assert post_audit.total_diffs == 0
    remaining = await store.list_indexed(category_id=_CAT, provider_id=_PROV)
    assert {e.resource_id for e in remaining} == {"r1", "r2", "r3"}
    actual_paths = {e.path for e in remaining}
    expected_paths = {e.path for e in golden}
    assert actual_paths == expected_paths
