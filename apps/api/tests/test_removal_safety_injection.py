"""R1 supplement: removal safety injection tests.

Verifies that P0 invariants around destructive removal are not violated under
various fault conditions per V2 doc section 57 and audit-tests-4 P0 gap item 4.
Uses FaultInjector + AListProviderAdapter + ReconcileService to confirm that
anomalous provider responses (null content, malformed payloads, 500s, timeouts,
403s, missing roots, multi-worker failures, empty snapshots, partial scans)
never trigger mass deletion of previously-indexed entries.

Each test follows the prescribed pattern:
1. Populate the store with entries from a prior healthy (complete) scan.
2. Inject a fault into the provider via FaultInjector.
3. Run scan + reconcile under the fault.
4. Assert that previously-indexed entries are not deleted.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from cloudsite.alist import AListError
from cloudsite.modules.indexing.application.reconcile import (
    ReconcileService,
    SHRINK_RATIO,
)
from cloudsite.modules.indexing.application.scan_category import (
    ScanCategoryService,
)
from cloudsite.modules.indexing.infrastructure.alist_adapter import (
    AListProviderAdapter,
)
from cloudsite.modules.indexing.infrastructure.repository import IndexedEntry
from cloudsite.modules.providers.contracts.public import ProviderScanRoot

from fault_injection import FaultInjector


# ---------------------------------------------------------------------------
# Test fakes
# ---------------------------------------------------------------------------

class FakeProvider:
    """ProviderScanPort fake backed by an in-memory directory tree."""

    def __init__(self, tree: dict[str, list[dict[str, Any]]]) -> None:
        self._tree = tree
        self.list_calls: list[str] = []

    async def list_path(
        self,
        path: str,
        refresh: bool = False,
        strict: bool = False,
    ) -> list[dict[str, Any]]:
        self.list_calls.append(path)
        return list(self._tree.get(path, []))

    async def get_metadata(self, path: str) -> dict[str, Any]:
        return {"name": path.rsplit("/", 1)[-1]}


class _RemovalTrackingStore:
    """In-memory IndexingStore that records every remove() call.

    Implements the IndexingStore protocol so ReconcileService can depend on
    it without touching a real database.  Removals are tracked so tests can
    assert the P0 invariant: destructive remove() is never invoked under
    anomalous provider behavior.
    """

    def __init__(self) -> None:
        self._entries: dict[str, IndexedEntry] = {}
        self.removed_ids: list[str] = []
        self.remove_call_count: int = 0
        self.upsert_call_count: int = 0

    async def list_indexed(
        self, *, category_id: str, provider_id: str
    ) -> list[IndexedEntry]:
        return [
            e
            for e in self._entries.values()
            if e.category_id == category_id and e.provider_id == provider_id
        ]

    async def upsert(self, entries: list[IndexedEntry]) -> int:
        self.upsert_call_count += 1
        for e in entries:
            self._entries[e.resource_id] = e
        return len(entries)

    async def remove(self, resource_ids: list[str]) -> int:
        self.remove_call_count += 1
        self.removed_ids.extend(resource_ids)
        removed = 0
        for rid in resource_ids:
            if rid in self._entries:
                del self._entries[rid]
                removed += 1
        return removed

    async def touch_unchanged(self, resource_ids: list[str]) -> int:
        return len(resource_ids)

    def existing_ids(self) -> set[str]:
        return set(self._entries.keys())


# ---------------------------------------------------------------------------
# Tree builders
# ---------------------------------------------------------------------------

def _make_tree() -> dict[str, list[dict[str, Any]]]:
    """Build a test tree:

    /root
      /a (dir)
        /a1 (file)
        /a2 (file)
        /sub (dir)
          /deep.zip (file)
      /b (dir)
        /b1 (file)
      /c (file)
    """
    return {
        "/root": [
            {"name": "a", "is_dir": True},
            {"name": "b", "is_dir": True},
            {"name": "c", "is_dir": False, "size": 100},
        ],
        "/root/a": [
            {"name": "a1", "is_dir": False, "size": 10},
            {"name": "a2", "is_dir": False, "size": 20},
            {"name": "sub", "is_dir": True},
        ],
        "/root/a/sub": [
            {"name": "deep.zip", "is_dir": False, "size": 5},
        ],
        "/root/b": [
            {"name": "b1", "is_dir": False, "size": 30},
        ],
    }


def _make_large_tree(
    num_dirs: int = 20, files_per_dir: int = 5
) -> dict[str, list[dict[str, Any]]]:
    tree: dict[str, list[dict[str, Any]]] = {
        "/root": [{"name": f"d{i}", "is_dir": True} for i in range(num_dirs)]
    }
    for i in range(num_dirs):
        tree[f"/root/d{i}"] = [
            {"name": f"f{j}", "is_dir": False, "size": j * 100}
            for j in range(files_per_dir)
        ]
    return tree


def _make_root(root_mapping_id: int = 1) -> ProviderScanRoot:
    return ProviderScanRoot(
        root_mapping_id=root_mapping_id,
        content_type="software",
        storage_path="/root",
        display_name="Root",
    )


CATEGORY_ID = "root:1"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _scan_and_reconcile(
    adapter: AListProviderAdapter,
    store: _RemovalTrackingStore,
    category_id: str = CATEGORY_ID,
) -> tuple[Any, Any]:
    """Run one scan + reconcile pass and return both results."""
    scan_service = ScanCategoryService(adapter)
    reconcile_service = ReconcileService(store)
    scan_result = await scan_service.scan(category_id)
    reconcile_result = await reconcile_service.reconcile(scan_result.snapshot)
    return scan_result, reconcile_result


async def _populate_store(
    store: _RemovalTrackingStore,
    tree: dict[str, list[dict[str, Any]]],
) -> set[str]:
    """Run a healthy scan+reconcile to populate the store.

    Returns the set of resource_ids that should be preserved by subsequent
    fault-injected passes.
    """
    provider = FakeProvider(tree)
    adapter = AListProviderAdapter(provider, [_make_root()])
    await _scan_and_reconcile(adapter, store)
    return store.existing_ids()


# ---------------------------------------------------------------------------
# 1. content=null response
# ---------------------------------------------------------------------------

async def test_content_null_no_mass_delete() -> None:
    """content=null response (empty list_path) does not trigger mass delete."""
    tree = _make_tree()
    store = _RemovalTrackingStore()
    existing_ids = await _populate_store(store, tree)
    assert len(existing_ids) >= 9

    provider = FakeProvider(tree)
    injector = FaultInjector(provider).return_empty_on_path("/root")
    adapter = AListProviderAdapter(injector, [_make_root()])

    _, reconcile_result = await _scan_and_reconcile(adapter, store)

    assert reconcile_result.shrink_suppressed is True
    assert reconcile_result.writes.removed == 0
    assert store.remove_call_count == 0
    assert existing_ids.issubset(store.existing_ids())


# ---------------------------------------------------------------------------
# 2. malformed response
# ---------------------------------------------------------------------------

async def test_malformed_response_no_mass_delete() -> None:
    """Malformed provider response does not trigger mass delete."""
    tree = _make_tree()
    store = _RemovalTrackingStore()
    existing_ids = await _populate_store(store, tree)

    provider = FakeProvider(tree)
    injector = FaultInjector(provider).return_malformed_on_path("/root")
    adapter = AListProviderAdapter(injector, [_make_root()])

    with pytest.raises(Exception):
        await _scan_and_reconcile(adapter, store)

    assert store.remove_call_count == 0
    assert existing_ids.issubset(store.existing_ids())


# ---------------------------------------------------------------------------
# 3. mid-directory 500
# ---------------------------------------------------------------------------

async def test_mid_dir_500_no_mass_delete() -> None:
    """A 500 on a mid-level directory skips that dir; no mass delete."""
    tree = _make_tree()
    store = _RemovalTrackingStore()
    existing_ids = await _populate_store(store, tree)

    provider = FakeProvider(tree)
    injector = FaultInjector(provider).fail_on_path(
        "/root/b", AListError("internal error", "AL-500", status_code=500)
    )
    adapter = AListProviderAdapter(injector, [_make_root()])

    scan_result, reconcile_result = await _scan_and_reconcile(adapter, store)

    assert scan_result.snapshot.pagination_complete is False
    assert reconcile_result.writes.removed == 0
    assert reconcile_result.suppressed_removals > 0
    assert store.remove_call_count == 0
    assert existing_ids.issubset(store.existing_ids())


# ---------------------------------------------------------------------------
# 4. timeout
# ---------------------------------------------------------------------------

async def test_timeout_no_mass_delete() -> None:
    """A timeout does not trigger mass delete of existing entries."""
    tree = _make_tree()
    store = _RemovalTrackingStore()
    existing_ids = await _populate_store(store, tree)

    provider = FakeProvider(tree)
    injector = FaultInjector(provider).fail_on_path(
        "/root/a", TimeoutError("upstream timeout")
    )
    adapter = AListProviderAdapter(injector, [_make_root()])

    with pytest.raises(TimeoutError):
        await _scan_and_reconcile(adapter, store)

    assert store.remove_call_count == 0
    assert existing_ids.issubset(store.existing_ids())


# ---------------------------------------------------------------------------
# 5. 403 forbidden
# ---------------------------------------------------------------------------

async def test_403_no_mass_delete() -> None:
    """A 403 on the root does not trigger mass delete."""
    tree = _make_tree()
    store = _RemovalTrackingStore()
    existing_ids = await _populate_store(store, tree)

    provider = FakeProvider(tree)
    injector = FaultInjector(provider).fail_on_path(
        "/root", AListError("forbidden", "AL-403", status_code=403)
    )
    adapter = AListProviderAdapter(injector, [_make_root()])

    scan_result, reconcile_result = await _scan_and_reconcile(adapter, store)

    assert scan_result.snapshot.pagination_complete is False
    assert reconcile_result.writes.removed == 0
    assert reconcile_result.suppressed_removals > 0
    assert store.remove_call_count == 0
    assert existing_ids.issubset(store.existing_ids())


# ---------------------------------------------------------------------------
# 6. root missing
# ---------------------------------------------------------------------------

async def test_root_missing_no_mass_delete() -> None:
    """Root missing (provider error on root) does not trigger mass delete."""
    tree = _make_tree()
    store = _RemovalTrackingStore()
    existing_ids = await _populate_store(store, tree)

    provider = FakeProvider(tree)
    injector = FaultInjector(provider).fail_on_path(
        "/root", AListError("not found", "AL-404", status_code=404)
    )
    adapter = AListProviderAdapter(injector, [_make_root()])

    scan_result, reconcile_result = await _scan_and_reconcile(adapter, store)

    assert scan_result.snapshot.pagination_complete is False
    assert reconcile_result.writes.removed == 0
    assert store.remove_call_count == 0
    assert existing_ids.issubset(store.existing_ids())


# ---------------------------------------------------------------------------
# 7. multi-worker simultaneous failure
# ---------------------------------------------------------------------------

async def test_multi_worker_simultaneous_failure() -> None:
    """Multiple workers failing simultaneously does not trigger mass delete."""
    tree = _make_large_tree(num_dirs=20, files_per_dir=5)
    store = _RemovalTrackingStore()
    existing_ids = await _populate_store(store, tree)
    assert len(existing_ids) >= 100

    provider = FakeProvider(tree)
    injector = FaultInjector(provider)
    for i in range(5):
        injector.fail_on_path(
            f"/root/d{i}", AListError("boom", "AL-500", status_code=500)
        )
    adapter = AListProviderAdapter(injector, [_make_root()])

    scan_result, reconcile_result = await _scan_and_reconcile(adapter, store)

    assert scan_result.snapshot.pagination_complete is False
    assert reconcile_result.writes.removed == 0
    assert reconcile_result.suppressed_removals > 0
    assert store.remove_call_count == 0
    assert existing_ids.issubset(store.existing_ids())


# ---------------------------------------------------------------------------
# 8. shrink guard with real adapter
# ---------------------------------------------------------------------------

async def test_shrink_guard_with_real_adapter() -> None:
    """Real adapter + empty snapshot triggers shrink guard; no mass delete."""
    tree = _make_large_tree(num_dirs=20, files_per_dir=5)
    store = _RemovalTrackingStore()
    existing_ids = await _populate_store(store, tree)
    existing_count = len(existing_ids)
    assert existing_count >= 100

    provider = FakeProvider(tree)
    injector = FaultInjector(provider).return_empty_on_path("/root")
    adapter = AListProviderAdapter(injector, [_make_root()])

    scan_result, reconcile_result = await _scan_and_reconcile(adapter, store)

    assert scan_result.snapshot.pagination_complete is True
    assert reconcile_result.shrink_suppressed is True
    assert reconcile_result.writes.removed == 0
    assert store.remove_call_count == 0
    assert existing_ids.issubset(store.existing_ids())


# ---------------------------------------------------------------------------
# 9. partial scan
# ---------------------------------------------------------------------------

async def test_partial_scan_no_removal() -> None:
    """Partial scan (pagination_complete=False) never issues removal writes."""
    tree = _make_tree()
    store = _RemovalTrackingStore()
    existing_ids = await _populate_store(store, tree)

    provider = FakeProvider(tree)
    injector = FaultInjector(provider).fail_on_path(
        "/root/a", AListError("partial", "AL-500", status_code=500)
    )
    adapter = AListProviderAdapter(injector, [_make_root()])

    scan_result, reconcile_result = await _scan_and_reconcile(adapter, store)

    assert scan_result.snapshot.pagination_complete is False
    assert reconcile_result.writes.removed == 0
    assert reconcile_result.suppressed_removals > 0
    assert store.remove_call_count == 0
    assert existing_ids.issubset(store.existing_ids())
