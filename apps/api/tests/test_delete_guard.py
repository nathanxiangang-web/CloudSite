"""R0 PR 02: destructive delete guard regression tests.

Covers the P0-1 fix (empty AList snapshot + pagination_complete=True no
longer wipes the index) and the P1-1 fix (AList directory failures mark
the scan incomplete so reconcile suppresses removals).
"""
from __future__ import annotations

import logging

import pytest

from cloudsite.alist import AListError
from cloudsite.modules.indexing.application.reconcile import ReconcileService
from cloudsite.modules.indexing.domain.snapshot import CategorySnapshot, SnapshotEntry
from cloudsite.modules.indexing.infrastructure.alist_adapter import AListProviderAdapter
from cloudsite.modules.indexing.infrastructure.repository import IndexedEntry
from cloudsite.modules.providers.contracts.public import ProviderScanRoot


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


def _snap(rid: str, path: str) -> SnapshotEntry:
    return SnapshotEntry(resource_id=rid, path=path, name=rid)


def _indexed(rid: str, path: str) -> IndexedEntry:
    return IndexedEntry(
        resource_id=rid, category_id="cat", provider_id="prov",
        path=path, name=rid,
    )


# --- P0-1: empty snapshot must not trigger mass delete ---

async def test_empty_snapshot_no_mass_delete():
    existing = [_indexed("a", "/a"), _indexed("b", "/b"), _indexed("c", "/c")]
    store = _FakeIndexingStore(existing=existing)
    service = ReconcileService(store)

    snapshot = CategorySnapshot(
        category_id="cat", provider_id="prov",
        entries=[], pagination_complete=True,
    )
    result = await service.reconcile(snapshot)

    assert store.remove_calls == []
    assert result.writes.removed == 0
    assert result.suppressed_removals == 3
    assert result.shrink_suppressed is True


# --- shrink threshold: removed > 10% existing is suppressed ---

async def test_shrink_threshold_suppresses():
    # 20 existing, 5 removed -> 25% > 10% -> suppressed.
    existing = [_indexed(f"r{i}", f"/r{i}") for i in range(20)]
    store = _FakeIndexingStore(existing=existing)
    service = ReconcileService(store)

    kept = [_snap(f"r{i}", f"/r{i}") for i in range(15)]
    snapshot = CategorySnapshot(
        category_id="cat", provider_id="prov",
        entries=kept, pagination_complete=True,
    )
    result = await service.reconcile(snapshot)

    assert store.remove_calls == []
    assert result.writes.removed == 0
    assert result.suppressed_removals == 5
    assert result.shrink_suppressed is True


# --- normal removal: removed <= 10% existing is allowed ---

async def test_normal_removal_allowed():
    # 20 existing, 2 removed -> 10% == threshold, not strictly greater,
    # so the destructive removal is allowed.
    existing = [_indexed(f"r{i}", f"/r{i}") for i in range(20)]
    store = _FakeIndexingStore(existing=existing)
    service = ReconcileService(store)

    kept = [_snap(f"r{i}", f"/r{i}") for i in range(18)]
    snapshot = CategorySnapshot(
        category_id="cat", provider_id="prov",
        entries=kept, pagination_complete=True,
    )
    result = await service.reconcile(snapshot)

    assert len(store.remove_calls) == 1
    assert result.writes.removed == 2
    assert result.suppressed_removals == 0
    assert result.shrink_suppressed is False


async def test_normal_removal_allowed_small_set():
    # 5 existing, 1 removed -> 1 <= max(1, 0.5)=1, allowed.
    existing = [_indexed(f"r{i}", f"/r{i}") for i in range(5)]
    store = _FakeIndexingStore(existing=existing)
    service = ReconcileService(store)

    kept = [_snap(f"r{i}", f"/r{i}") for i in range(4)]
    snapshot = CategorySnapshot(
        category_id="cat", provider_id="prov",
        entries=kept, pagination_complete=True,
    )
    result = await service.reconcile(snapshot)

    assert len(store.remove_calls) == 1
    assert result.writes.removed == 1
    assert result.shrink_suppressed is False


# --- partial scan: pagination_complete=False never removes ---

async def test_partial_scan_no_removal():
    existing = [_indexed("a", "/a"), _indexed("b", "/b")]
    store = _FakeIndexingStore(existing=existing)
    service = ReconcileService(store)

    snapshot = CategorySnapshot(
        category_id="cat", provider_id="prov",
        entries=[], pagination_complete=False,
    )
    result = await service.reconcile(snapshot)

    assert store.remove_calls == []
    assert result.writes.removed == 0
    assert result.suppressed_removals == 2
    assert result.shrink_suppressed is False


# --- P1-1: AList directory failure marks pagination_complete=False ---

class _FlakyProvider:
    """Returns a sub-folder at root, then raises AListError on the sub-folder."""

    def __init__(self) -> None:
        self.list_calls: list[str] = []

    async def list_path(self, path: str):
        self.list_calls.append(path)
        if path == "/":
            return [{"name": "sub", "is_dir": True}]
        raise AListError(f"simulated timeout listing {path}", "AL-005")

    async def get_metadata(self, path: str):
        return {"name": path.rsplit("/", 1)[-1]}


async def test_alist_error_marks_pagination_incomplete():
    root = ProviderScanRoot(
        root_mapping_id=1,
        content_type="file",
        storage_path="/",
        display_name="root",
    )
    adapter = AListProviderAdapter(_FlakyProvider(), [root])

    entries, cursor, pagination_complete = await adapter.scan_category("root:1")

    assert pagination_complete is False
    assert cursor is None
    # Root folder and the discovered sub-folder are still emitted; only the
    # sub-folder's children are missing because its list_path failed.
    names = {e.name for e in entries}
    assert "root" in names
    assert "sub" in names


async def test_alist_error_emits_warning_log(caplog: pytest.LogCaptureFixture):
    root = ProviderScanRoot(
        root_mapping_id=1,
        content_type="file",
        storage_path="/",
        display_name="root",
    )
    adapter = AListProviderAdapter(_FlakyProvider(), [root])

    with caplog.at_level(logging.ERROR, logger="cloudsite.modules.indexing.infrastructure.alist_adapter"):
        await adapter.scan_category("root:1")

    assert any("marking scan incomplete" in record.message for record in caplog.records)


async def test_shrink_suppressed_emits_warning_log(caplog: pytest.LogCaptureFixture):
    existing = [_indexed(f"r{i}", f"/r{i}") for i in range(10)]
    store = _FakeIndexingStore(existing=existing)
    service = ReconcileService(store)

    snapshot = CategorySnapshot(
        category_id="cat", provider_id="prov",
        entries=[], pagination_complete=True,
    )
    with caplog.at_level(logging.WARNING, logger="cloudsite.modules.indexing.application.reconcile"):
        result = await service.reconcile(snapshot)

    assert result.shrink_suppressed is True
    assert any("anomalous shrink detected" in record.message for record in caplog.records)
