"""R1 acceptance: root missing / permission denied / shrink guard tests.

Covers V2 docs sections 80-83 (audit-tests-4 P0 gap item 5):

- Root missing (V2 S80): root path does not exist on the provider -> the
  scan for that root is marked degraded (pagination_complete=False) and
  reconcile must NOT delete previously indexed entries.
- Permission denied (V2 S81): a 403 from the provider marks the scan
  partial (pagination_complete=False) so reconcile suppresses removals;
  one inaccessible directory must not abort scanning of sibling dirs.
- Shrink guard (V2 S82-83): reconcile suppresses destructive removals
  when the fraction of removed entries exceeds 10% of existing, with a
  floor of max(1, 10%) so small sets can still lose a single entry.
- Combination: partial scan + shrink guard, and multi-root where one
  root shrinks while another reconciles normally.
"""
from __future__ import annotations

import logging
from typing import Any

import pytest

from cloudsite.alist import AListError
from cloudsite.modules.indexing.application.reconcile import (
    SHRINK_RATIO,
    ReconcileService,
)
from cloudsite.modules.indexing.domain.snapshot import (
    CategorySnapshot,
    SnapshotEntry,
)
from cloudsite.modules.indexing.infrastructure.alist_adapter import (
    AListProviderAdapter,
)
from cloudsite.modules.indexing.infrastructure.legacy_bridge import run_indexing_v2
from cloudsite.modules.indexing.infrastructure.provider_adapter import (
    ProviderCapabilities,
)
from cloudsite.modules.indexing.infrastructure.repository import IndexedEntry
from cloudsite.modules.providers.contracts.public import ProviderScanRoot


# ---------------------------------------------------------------------------
# Shared in-memory fakes
# ---------------------------------------------------------------------------


class _FakeIndexingStore:
    """In-memory IndexingStore that records every write call for assertions."""

    def __init__(self, existing: list[IndexedEntry] | None = None) -> None:
        self._data: dict[str, IndexedEntry] = {
            e.resource_id: e for e in (existing or [])
        }
        self.upsert_calls: list[list[IndexedEntry]] = []
        self.remove_calls: list[list[str]] = []
        self.touch_calls: list[list[str]] = []

    async def list_indexed(
        self, *, category_id: str, provider_id: str
    ) -> list[IndexedEntry]:
        return [
            e
            for e in self._data.values()
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


def _snap(rid: str, path: str) -> SnapshotEntry:
    return SnapshotEntry(resource_id=rid, path=path, name=rid)


def _indexed(rid: str, path: str, *, category_id: str = "cat") -> IndexedEntry:
    return IndexedEntry(
        resource_id=rid,
        category_id=category_id,
        provider_id="prov",
        path=path,
        name=rid,
    )


class _MissingRootProvider:
    """ProviderScanPort fake whose every list_path raises AListError (404)."""

    async def list_path(
        self, path: str, refresh: bool = False, strict: bool = False
    ) -> list[dict[str, Any]]:
        raise AListError(f"path not found: {path}", "AL-404", status_code=404)

    async def get_metadata(self, path: str) -> dict[str, Any]:
        raise AListError(f"path not found: {path}", "AL-404", status_code=404)


class _ForbiddenProvider:
    """ProviderScanPort fake that returns 403 AListError on every list_path."""

    async def list_path(
        self, path: str, refresh: bool = False, strict: bool = False
    ) -> list[dict[str, Any]]:
        raise AListError(
            f"permission denied: {path}", "AL-403", status_code=403
        )

    async def get_metadata(self, path: str) -> dict[str, Any]:
        raise AListError(
            f"permission denied: {path}", "AL-403", status_code=403
        )


def _root(root_mapping_id: int, storage_path: str) -> ProviderScanRoot:
    return ProviderScanRoot(
        root_mapping_id=root_mapping_id,
        content_type="file",
        storage_path=storage_path,
        display_name=f"root-{root_mapping_id}",
    )


# ---------------------------------------------------------------------------
# Root missing scenarios (V2 S80)
# ---------------------------------------------------------------------------


async def test_root_missing_marks_degraded():
    """Root path does not exist -> scan marks pagination_complete=False
    (degraded) and reconcile must not delete previously indexed entries."""
    root = _root(1, "/missing")
    adapter = AListProviderAdapter(_MissingRootProvider(), [root])

    entries, cursor, pagination_complete = await adapter.scan_category("root:1")

    # The root is marked degraded: pagination_complete is False.
    assert pagination_complete is False
    assert cursor is None
    # The root folder entry is still emitted so operators can see it.
    assert len(entries) == 1
    assert entries[0].path == "/missing"

    # Reconcile with previously indexed children must not remove them.
    existing = [
        _indexed("r1", "/missing/r1", category_id="root:1"),
        _indexed("r2", "/missing/r2", category_id="root:1"),
        _indexed("r3", "/missing/r3", category_id="root:1"),
    ]
    store = _FakeIndexingStore(existing=existing)
    service = ReconcileService(store)

    snapshot = CategorySnapshot(
        category_id="root:1",
        provider_id="prov",
        entries=entries,
        pagination_complete=pagination_complete,
    )
    result = await service.reconcile(snapshot)

    assert store.remove_calls == []
    assert result.writes.removed == 0
    assert result.suppressed_removals == 3
    assert result.pagination_complete is False


async def test_root_missing_other_roots_unaffected():
    """One root missing must not affect scanning of other roots."""
    missing_root = _root(1, "/missing")
    ok_root = _root(2, "/ok")

    class _MixedProvider:
        async def list_path(
            self, path: str, refresh: bool = False, strict: bool = False
        ) -> list[dict[str, Any]]:
            if path == "/missing":
                raise AListError(
                    f"path not found: {path}", "AL-404", status_code=404
                )
            if path == "/ok":
                return [{"name": "file.txt", "is_dir": False, "size": 42}]
            return []

        async def get_metadata(self, path: str) -> dict[str, Any]:
            return {"name": path.rsplit("/", 1)[-1]}

    adapter = AListProviderAdapter(_MixedProvider(), [missing_root, ok_root])

    missing_entries, _, missing_complete = await adapter.scan_category("root:1")
    ok_entries, _, ok_complete = await adapter.scan_category("root:2")

    # Missing root is degraded.
    assert missing_complete is False
    # The healthy root is fully scanned and unaffected.
    assert ok_complete is True
    ok_paths = {e.path for e in ok_entries}
    assert "/ok" in ok_paths
    assert "/ok/file.txt" in ok_paths


async def test_root_missing_no_cascade_delete():
    """Root missing must not trigger cascade deletion of indexed children."""
    root = _root(1, "/missing")
    adapter = AListProviderAdapter(_MissingRootProvider(), [root])

    entries, _, pagination_complete = await adapter.scan_category("root:1")
    assert pagination_complete is False

    # Seed the store with children that used to live under the missing root.
    existing = [
        _indexed(f"child-{i}", f"/missing/child-{i}", category_id="root:1")
        for i in range(10)
    ]
    store = _FakeIndexingStore(existing=existing)
    service = ReconcileService(store)

    snapshot = CategorySnapshot(
        category_id="root:1",
        provider_id="prov",
        entries=entries,
        pagination_complete=pagination_complete,
    )
    result = await service.reconcile(snapshot)

    # No remove calls at all -> no cascade delete.
    assert store.remove_calls == []
    assert result.writes.removed == 0
    # All 10 children are reported as suppressed removals, not deleted.
    assert result.suppressed_removals == 10
    # The store still holds every original child entry (the root folder
    # entry from the scan is upserted as an addition, which is fine).
    for i in range(10):
        assert f"child-{i}" in store._data


# ---------------------------------------------------------------------------
# Permission denied scenarios (V2 S81)
# ---------------------------------------------------------------------------


async def test_permission_denied_no_delete():
    """A 403 from the provider must not delete already indexed entries."""
    root = _root(1, "/secure")
    adapter = AListProviderAdapter(_ForbiddenProvider(), [root])

    entries, _, pagination_complete = await adapter.scan_category("root:1")

    # 403 marks the scan partial.
    assert pagination_complete is False

    existing = [
        _indexed("s1", "/secure/s1", category_id="root:1"),
        _indexed("s2", "/secure/s2", category_id="root:1"),
    ]
    store = _FakeIndexingStore(existing=existing)
    service = ReconcileService(store)

    snapshot = CategorySnapshot(
        category_id="root:1",
        provider_id="prov",
        entries=entries,
        pagination_complete=pagination_complete,
    )
    result = await service.reconcile(snapshot)

    assert store.remove_calls == []
    assert result.writes.removed == 0
    assert result.suppressed_removals == 2
    assert result.pagination_complete is False


async def test_permission_denied_marks_partial():
    """A 403 must mark pagination_complete=False so reconcile knows the scan
    is partial."""
    root = _root(1, "/secure")
    adapter = AListProviderAdapter(_ForbiddenProvider(), [root])

    _, _, pagination_complete = await adapter.scan_category("root:1")

    assert pagination_complete is False


async def test_permission_denied_other_dirs_continue():
    """A 403 on one directory must not prevent scanning of sibling dirs.

    The adapter concurrently lists sub-directories; if one raises a 403 the
    scan must continue for the others, emit their entries, and mark the
    overall scan as partial (pagination_complete=False).
    """
    root = _root(1, "/parent")

    class _PartialForbiddenProvider:
        async def list_path(
            self, path: str, refresh: bool = False, strict: bool = False
        ) -> list[dict[str, Any]]:
            if path == "/parent":
                return [
                    {"name": "open", "is_dir": True},
                    {"name": "locked", "is_dir": True},
                ]
            if path == "/parent/open":
                return [{"name": "readable.txt", "is_dir": False, "size": 1}]
            if path == "/parent/locked":
                raise AListError(
                    "permission denied", "AL-403", status_code=403
                )
            return []

        async def get_metadata(self, path: str) -> dict[str, Any]:
            return {"name": path.rsplit("/", 1)[-1]}

    adapter = AListProviderAdapter(_PartialForbiddenProvider(), [root])

    entries, _, pagination_complete = await adapter.scan_category("root:1")

    # The locked dir's 403 marks the scan partial.
    assert pagination_complete is False
    # But the open dir's entries are still emitted.
    paths = {e.path for e in entries}
    assert "/parent" in paths
    assert "/parent/open" in paths
    assert "/parent/open/readable.txt" in paths
    assert "/parent/locked" in paths  # the folder itself is still listed


# ---------------------------------------------------------------------------
# Shrink guard scenarios (V2 S82-83)
# ---------------------------------------------------------------------------


async def test_shrink_10_percent_boundary():
    """Exactly 10% shrink is allowed (boundary: removed == threshold)."""
    # 20 existing, 2 removed -> 10% == max(1, 0.1*20)=2, not strictly
    # greater, so the destructive removal is allowed.
    existing = [_indexed(f"r{i}", f"/r{i}") for i in range(20)]
    store = _FakeIndexingStore(existing=existing)
    service = ReconcileService(store)

    kept = [_snap(f"r{i}", f"/r{i}") for i in range(18)]
    snapshot = CategorySnapshot(
        category_id="cat",
        provider_id="prov",
        entries=kept,
        pagination_complete=True,
    )
    result = await service.reconcile(snapshot)

    assert len(store.remove_calls) == 1
    assert result.writes.removed == 2
    assert result.suppressed_removals == 0
    assert result.shrink_suppressed is False


async def test_shrink_11_percent_suppressed():
    """11% shrink exceeds the 10% threshold -> removal suppressed."""
    # 100 existing, 11 removed -> 11% > max(1, 0.1*100)=10 -> suppressed.
    existing = [_indexed(f"r{i}", f"/r{i}") for i in range(100)]
    store = _FakeIndexingStore(existing=existing)
    service = ReconcileService(store)

    kept = [_snap(f"r{i}", f"/r{i}") for i in range(89)]
    snapshot = CategorySnapshot(
        category_id="cat",
        provider_id="prov",
        entries=kept,
        pagination_complete=True,
    )
    result = await service.reconcile(snapshot)

    assert store.remove_calls == []
    assert result.writes.removed == 0
    assert result.suppressed_removals == 11
    assert result.shrink_suppressed is True


async def test_shrink_small_set_floor():
    """Small set: max(1, 10%) = 1, so removing exactly 1 entry is allowed."""
    # 3 existing, 1 removed -> threshold = max(1, 0.3) = 1,
    # 1 > 1 is False -> allowed.
    existing = [_indexed(f"r{i}", f"/r{i}") for i in range(3)]
    store = _FakeIndexingStore(existing=existing)
    service = ReconcileService(store)

    kept = [_snap("r0", "/r0"), _snap("r1", "/r1")]
    snapshot = CategorySnapshot(
        category_id="cat",
        provider_id="prov",
        entries=kept,
        pagination_complete=True,
    )
    result = await service.reconcile(snapshot)

    assert len(store.remove_calls) == 1
    assert result.writes.removed == 1
    assert result.suppressed_removals == 0
    assert result.shrink_suppressed is False


async def test_shrink_guard_logs_warning(caplog: pytest.LogCaptureFixture):
    """When the shrink guard fires, a WARNING must be logged."""
    existing = [_indexed(f"r{i}", f"/r{i}") for i in range(20)]
    store = _FakeIndexingStore(existing=existing)
    service = ReconcileService(store)

    # 20 existing, 5 removed -> 25% > 10% -> suppressed.
    kept = [_snap(f"r{i}", f"/r{i}") for i in range(15)]
    snapshot = CategorySnapshot(
        category_id="cat",
        provider_id="prov",
        entries=kept,
        pagination_complete=True,
    )
    with caplog.at_level(
        logging.WARNING,
        logger="cloudsite.modules.indexing.application.reconcile",
    ):
        result = await service.reconcile(snapshot)

    assert result.shrink_suppressed is True
    assert any(
        "anomalous shrink detected" in record.message
        for record in caplog.records
        if record.levelno == logging.WARNING
    )


async def test_shrink_guard_sets_flag():
    """When the shrink guard fires, shrink_suppressed must be True."""
    existing = [_indexed(f"r{i}", f"/r{i}") for i in range(50)]
    store = _FakeIndexingStore(existing=existing)
    service = ReconcileService(store)

    # 50 existing, 10 removed -> 20% > 10% -> suppressed.
    kept = [_snap(f"r{i}", f"/r{i}") for i in range(40)]
    snapshot = CategorySnapshot(
        category_id="cat",
        provider_id="prov",
        entries=kept,
        pagination_complete=True,
    )
    result = await service.reconcile(snapshot)

    assert result.shrink_suppressed is True
    assert result.writes.removed == 0
    assert result.suppressed_removals == 10


# ---------------------------------------------------------------------------
# Combination scenarios
# ---------------------------------------------------------------------------


async def test_partial_scan_then_shrink_guard():
    """Partial scan (pagination_complete=False) takes precedence over the
    shrink guard: removals are suppressed but shrink_suppressed stays False
    because the suppression reason is the partial scan, not anomalous shrink.
    """
    # 20 existing, snapshot has 0 entries and pagination_complete=False.
    # Without the partial-scan guard the empty snapshot would be a 100%
    # shrink; the partial-scan branch must win and not set shrink_suppressed.
    existing = [_indexed(f"r{i}", f"/r{i}") for i in range(20)]
    store = _FakeIndexingStore(existing=existing)
    service = ReconcileService(store)

    snapshot = CategorySnapshot(
        category_id="cat",
        provider_id="prov",
        entries=[],
        pagination_complete=False,
    )
    result = await service.reconcile(snapshot)

    assert store.remove_calls == []
    assert result.writes.removed == 0
    assert result.suppressed_removals == 20
    # Partial scan suppresses removals; shrink_suppressed stays False.
    assert result.shrink_suppressed is False
    assert result.pagination_complete is False


class _CatalogAdapter:
    """ProviderAdapter fake backed by a per-category snapshot catalog.

    Each catalog value is (entries, pagination_complete). Used to drive
    run_indexing_v2 across multiple roots with independent scan outcomes.
    """

    def __init__(
        self,
        catalog: dict[str, tuple[list[SnapshotEntry], bool]],
        provider_id: str = "prov",
    ) -> None:
        self._catalog = catalog
        self._provider_id = provider_id
        self.last_scan_metrics: dict[str, int] = {
            "active_workers": 0,
            "dirs_done": 0,
            "dirs_pending": 0,
            "entries_discovered": 0,
        }

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(supports_scan=True)

    async def scan_category(
        self,
        category_id: str,
        *,
        cursor: str | None = None,
        limit: int | None = None,
        on_progress: Any = None,
        concurrency: int = 8,
    ) -> tuple[list[SnapshotEntry], str | None, bool]:
        entries, complete = self._catalog.get(category_id, ([], True))
        return list(entries), None, complete

    async def inspect(self, request: Any) -> Any:
        raise NotImplementedError


async def test_multi_root_one_shrink_other_normal():
    """One root hitting the shrink guard must not block normal removal in
    another root."""
    # Root "root:1" -> shrink scenario: 20 existing, 0 in snapshot (100%).
    # Root "root:2" -> normal: 10 existing, 8 in snapshot (20% removed but
    #   only 2 entries removed which is 20% > 10%, so also suppressed...
    #   let me make it 1 removed = 10% which is allowed).
    shrink_existing = [
        _indexed(f"s{i}", f"/s{i}", category_id="root:1") for i in range(20)
    ]
    normal_existing = [
        _indexed(f"n{i}", f"/n{i}", category_id="root:2") for i in range(10)
    ]
    store = _FakeIndexingStore(
        existing=shrink_existing + normal_existing
    )

    # Shrink root: empty snapshot, pagination_complete=True -> 100% shrink.
    shrink_entries: list[SnapshotEntry] = []
    # Normal root: 10 existing, 1 removed (10% == threshold) -> allowed.
    normal_entries = [_snap(f"n{i}", f"/n{i}") for i in range(9)]

    catalog = {
        "root:1": (shrink_entries, True),
        "root:2": (normal_entries, True),
    }
    adapter = _CatalogAdapter(catalog)

    result = await run_indexing_v2(
        adapter=adapter,
        store=store,
        category_ids=["root:1", "root:2"],
    )

    # Both categories are scanned (reconcile does not raise on shrink).
    assert result["status"] == "success"
    assert result["categories_scanned"] == 2
    # Shrink root: 20 suppressed, 0 removed.
    # Normal root: 1 removed, 0 suppressed.
    assert result["writes"]["removed"] == 1
    assert result["suppressed_removals"] == 20
    # The store must still hold all 20 shrink-root entries plus the 9
    # surviving normal-root entries.
    assert len(store._data) == 29


# ---------------------------------------------------------------------------
# Sanity check on the shrink ratio constant
# ---------------------------------------------------------------------------


def test_shrink_ratio_constant_is_10_percent():
    """The shrink guard threshold must be 10% (V2 S82)."""
    assert SHRINK_RATIO == 0.1
