"""R1 PR 07: concurrent consistency and idempotency acceptance tests.

Verifies V2 doc section 54 (concurrency consistency) and section 55
(idempotency):

- concurrency=1/2/8/16 produce identical inventory
- no duplicate staging rows, lost child dirs, parent count mismatch,
  queue deadlock, forever-pending tasks, or worker leaks
- two consecutive runs of the same provider snapshot: the second run
  reports added=changed=removed=0
- worker order and JSON key order do not produce phantom changes
"""
from __future__ import annotations

from typing import Any

import pytest

from cloudsite.modules.indexing.infrastructure.alist_adapter import (
    AListProviderAdapter,
    DIRECTORY_CONCURRENCY,
)
from cloudsite.modules.indexing.infrastructure.legacy_bridge import run_indexing_v2
from cloudsite.modules.indexing.infrastructure.repository import IndexedEntry
from cloudsite.modules.providers.contracts.public import ProviderScanRoot


# ---------------------------------------------------------------------------
# Fixture: FakeAListProvider with a 24-directory, 51-file tree
# ---------------------------------------------------------------------------


class FakeAListProvider:
    """ProviderScanPort fake backed by an in-memory directory tree.

    The tree is a dict mapping directory path -> list of item dicts.
    Each item dict has: name, is_dir, size (optional), modified (optional).
    """

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
        return [dict(item) for item in self._tree.get(path, [])]

    async def get_metadata(self, path: str) -> dict[str, Any]:
        return {"name": path.rsplit("/", 1)[-1]}


def _make_big_tree() -> dict[str, list[dict[str, Any]]]:
    """Build a tree with 24 directories and 51 files.

    Layout:
      /root
        top1.txt..top7.txt            (7 files)
        a..t                          (20 dirs)
      /root/a  a1.txt a2.txt a3.txt   (3 files)  sub1 sub2
      /root/b  b1.txt b2.txt          (2 files)  sub3
      /root/c  c1.txt c2.txt          (2 files)
      /root/d  d1.txt d2.txt d3.txt d4.txt (4 files)
      /root/e  e1.txt e2.txt          (2 files)
      /root/f  f1.txt f2.txt f3.txt   (3 files)
      /root/g  g1.txt                 (1 file)
      /root/h  h1.txt h2.txt          (2 files)
      /root/i  i1.txt                 (1 file)
      /root/j  j1.txt j2.txt j3.txt   (3 files)
      /root/k  k1.txt                 (1 file)
      /root/l  l1.txt l2.txt          (2 files)
      /root/m  m1.txt                 (1 file)
      /root/n  n1.txt n2.txt n3.txt   (3 files)
      /root/o  o1.txt                 (1 file)
      /root/p  p1.txt p2.txt          (2 files)
      /root/q  q1.txt                 (1 file)
      /root/r  r1.txt r2.txt r3.txt   (3 files)
      /root/s  s1.txt                 (1 file)
      /root/t  t1.txt t2.txt          (2 files)
      /root/a/sub1  deep1.zip deep2.zip (2 files)
      /root/a/sub2  deep3.zip           (1 file)
      /root/b/sub3  deep4.zip           (1 file)
    """
    tree: dict[str, list[dict[str, Any]]] = {}

    root_items: list[dict[str, Any]] = []
    for i in range(1, 8):
        root_items.append({"name": f"top{i}.txt", "is_dir": False, "size": 100 + i})
    for letter in "abcdefghijklmnopqrst":
        root_items.append({"name": letter, "is_dir": True})
    tree["/root"] = root_items

    file_counts = {
        "a": 3, "b": 2, "c": 2, "d": 4, "e": 2, "f": 3, "g": 1, "h": 2,
        "i": 1, "j": 3, "k": 1, "l": 2, "m": 1, "n": 3, "o": 1, "p": 2,
        "q": 1, "r": 3, "s": 1, "t": 2,
    }
    for letter, count in file_counts.items():
        items: list[dict[str, Any]] = []
        for i in range(1, count + 1):
            items.append({"name": f"{letter}{i}.txt", "is_dir": False, "size": 10 + i})
        tree[f"/root/{letter}"] = items

    tree["/root/a"].extend([
        {"name": "sub1", "is_dir": True},
        {"name": "sub2", "is_dir": True},
    ])
    tree["/root/a/sub1"] = [
        {"name": "deep1.zip", "is_dir": False, "size": 50},
        {"name": "deep2.zip", "is_dir": False, "size": 60},
    ]
    tree["/root/a/sub2"] = [
        {"name": "deep3.zip", "is_dir": False, "size": 70},
    ]
    tree["/root/b"].append({"name": "sub3", "is_dir": True})
    tree["/root/b/sub3"] = [
        {"name": "deep4.zip", "is_dir": False, "size": 80},
    ]

    return tree


EXPECTED_DIR_COUNT = 24
EXPECTED_FILE_COUNT = 51
EXPECTED_TOTAL_ENTRIES = EXPECTED_DIR_COUNT + EXPECTED_FILE_COUNT

EXPECTED_DIR_PATHS = {"/root"} | {
    f"/root/{letter}" for letter in "abcdefghijklmnopqrst"
} | {"/root/a/sub1", "/root/a/sub2", "/root/b/sub3"}


def _make_root() -> ProviderScanRoot:
    return ProviderScanRoot(
        root_mapping_id=1,
        content_type="software",
        storage_path="/root",
        display_name="Root",
    )


async def _scan(concurrency: int) -> tuple[list, bool, dict[str, int]]:
    provider = FakeAListProvider(_make_big_tree())
    adapter = AListProviderAdapter(provider, [_make_root()])
    entries, _, complete = await adapter.scan_category(
        "root:1", concurrency=concurrency
    )
    return entries, complete, adapter.last_scan_metrics


def _entry_paths(entries: list) -> set[str]:
    return {e.path for e in entries}


def _entry_ids(entries: list) -> set[str]:
    return {e.resource_id for e in entries}


# ---------------------------------------------------------------------------
# V2 section 54: Concurrency consistency acceptance
# ---------------------------------------------------------------------------


async def test_concurrency_1_2_8_16_identical_inventory():
    """Same fixture scanned with concurrency=1/2/8/16 yields identical inventory."""
    results: dict[int, list] = {}
    for concurrency in (1, 2, 8, 16):
        entries, complete, metrics = await _scan(concurrency)
        assert complete is True, f"concurrency={concurrency} did not complete"
        assert len(entries) == EXPECTED_TOTAL_ENTRIES, (
            f"concurrency={concurrency} found {len(entries)} entries, "
            f"expected {EXPECTED_TOTAL_ENTRIES}"
        )
        assert metrics["active_workers"] == 0
        assert metrics["dirs_pending"] == 0
        results[concurrency] = entries

    ref_paths = _entry_paths(results[1])
    ref_ids = _entry_ids(results[1])
    ref_order = [e.path for e in results[1]]

    for concurrency in (2, 8, 16):
        assert _entry_paths(results[concurrency]) == ref_paths
        assert _entry_ids(results[concurrency]) == ref_ids
        assert [e.path for e in results[concurrency]] == ref_order, (
            f"concurrency={concurrency} produced different entry order"
        )
        ref_by_path = {e.path: e for e in results[1]}
        for entry in results[concurrency]:
            ref = ref_by_path[entry.path]
            assert entry.resource_id == ref.resource_id
            assert entry.metadata["depth"] == ref.metadata["depth"]
            assert entry.metadata["parent_path"] == ref.metadata["parent_path"]
            assert entry.metadata["parent_id"] == ref.metadata["parent_id"]
            assert entry.metadata["is_dir"] == ref.metadata["is_dir"]
            assert entry.metadata["child_folder_count"] == ref.metadata["child_folder_count"]
            assert entry.metadata["resource_count"] == ref.metadata["resource_count"]


async def test_no_duplicate_staging_rows():
    """Concurrent scan produces no duplicate staging rows (paths or IDs)."""
    entries, _, _ = await _scan(concurrency=8)
    paths = [e.path for e in entries]
    ids = [e.resource_id for e in entries]
    assert len(paths) == len(set(paths)), "duplicate paths found"
    assert len(ids) == len(set(ids)), "duplicate resource_ids found"


async def test_no_lost_child_dirs():
    """All child directories in the fixture are discovered by the scan."""
    entries, _, _ = await _scan(concurrency=8)
    discovered_dirs = {e.path for e in entries if e.metadata["is_dir"]}
    assert discovered_dirs == EXPECTED_DIR_PATHS, (
        f"lost dirs: {EXPECTED_DIR_PATHS - discovered_dirs}, "
        f"extra dirs: {discovered_dirs - EXPECTED_DIR_PATHS}"
    )
    assert len(discovered_dirs) == EXPECTED_DIR_COUNT


async def test_no_parent_count_mismatch():
    """Parent relations are correct: parent_id and child counts match."""
    entries, _, _ = await _scan(concurrency=8)
    by_path = {e.path: e for e in entries}

    expected_child_folders: dict[str, int] = {}
    expected_child_resources: dict[str, int] = {}
    for entry in entries:
        parent_path = entry.metadata.get("parent_path")
        if parent_path is None:
            continue
        if entry.metadata["is_dir"]:
            expected_child_folders[parent_path] = expected_child_folders.get(parent_path, 0) + 1
        else:
            expected_child_resources[parent_path] = expected_child_resources.get(parent_path, 0) + 1

    for entry in entries:
        parent_path = entry.metadata.get("parent_path")
        parent_id = entry.metadata.get("parent_id")

        if parent_path is None:
            assert parent_id is None, f"root {entry.path} has unexpected parent_id"
        else:
            assert parent_path in by_path, (
                f"entry {entry.path} references missing parent {parent_path}"
            )
            parent = by_path[parent_path]
            assert parent_id == parent.resource_id, (
                f"entry {entry.path} parent_id={parent_id} != "
                f"parent.resource_id={parent.resource_id}"
            )

        actual_folders = expected_child_folders.get(entry.path, 0)
        actual_resources = expected_child_resources.get(entry.path, 0)
        assert entry.metadata["child_folder_count"] == actual_folders, (
            f"{entry.path}: child_folder_count={entry.metadata['child_folder_count']} "
            f"!= actual={actual_folders}"
        )
        assert entry.metadata["resource_count"] == actual_resources, (
            f"{entry.path}: resource_count={entry.metadata['resource_count']} "
            f"!= actual={actual_resources}"
        )


async def test_no_queue_deadlock():
    """Scan completes without deadlock (returns with all entries)."""
    entries, complete, _ = await _scan(concurrency=8)
    assert complete is True
    assert len(entries) == EXPECTED_TOTAL_ENTRIES
    assert len(entries) > 0


async def test_no_forever_pending():
    """No tasks remain forever pending: dirs_pending=0 and active_workers=0."""
    _, _, metrics = await _scan(concurrency=8)
    assert metrics["dirs_pending"] == 0, (
        f"dirs_pending={metrics['dirs_pending']} indicates stuck tasks"
    )
    assert metrics["active_workers"] == 0, (
        f"active_workers={metrics['active_workers']} indicates leaked workers"
    )
    assert metrics["dirs_done"] == EXPECTED_DIR_COUNT, (
        f"dirs_done={metrics['dirs_done']} != {EXPECTED_DIR_COUNT}"
    )


async def test_no_worker_leak():
    """All workers exit cleanly after scan completion."""
    entries, complete, metrics = await _scan(concurrency=16)
    assert complete is True
    assert metrics["active_workers"] == 0, (
        f"active_workers={metrics['active_workers']} workers leaked"
    )
    assert metrics["dirs_pending"] == 0
    assert len(entries) == EXPECTED_TOTAL_ENTRIES


# ---------------------------------------------------------------------------
# V2 section 55: Idempotency acceptance
# ---------------------------------------------------------------------------


class _InMemoryIndexingStore:
    """In-memory IndexingStore for idempotency tests."""

    def __init__(self, seeded: list[IndexedEntry] | None = None) -> None:
        self._entries: dict[str, IndexedEntry] = {
            e.resource_id: e for e in (seeded or [])
        }

    async def list_indexed(self, *, category_id: str, provider_id: str) -> list[IndexedEntry]:
        return [
            e for e in self._entries.values()
            if e.category_id == category_id and e.provider_id == provider_id
        ]

    async def upsert(self, entries: list[IndexedEntry]) -> int:
        for e in entries:
            self._entries[e.resource_id] = e
        return len(entries)

    async def remove(self, resource_ids: list[str]) -> int:
        removed = 0
        for rid in resource_ids:
            if rid in self._entries:
                del self._entries[rid]
                removed += 1
        return removed

    async def touch_unchanged(self, resource_ids: list[str]) -> int:
        return len(resource_ids)


async def test_idemp():
    """Two consecutive runs of the same snapshot: second run added=changed=removed=0."""
    provider_one = FakeAListProvider(_make_big_tree())
    adapter_one = AListProviderAdapter(provider_one, [_make_root()])
    store = _InMemoryIndexingStore()

    first = await run_indexing_v2(
        adapter=adapter_one,
        store=store,
        category_ids=["root:1"],
    )

    assert first["status"] == "success"
    assert first["writes"]["added"] == EXPECTED_TOTAL_ENTRIES, (
        f"first run added={first['writes']['added']} != {EXPECTED_TOTAL_ENTRIES}"
    )
    assert first["writes"]["changed"] == 0
    assert first["writes"]["removed"] == 0

    provider_two = FakeAListProvider(_make_big_tree())
    adapter_two = AListProviderAdapter(provider_two, [_make_root()])
    second = await run_indexing_v2(
        adapter=adapter_two,
        store=store,
        category_ids=["root:1"],
    )

    assert second["status"] == "success"
    assert second["writes"]["added"] == 0, (
        f"second run added={second['writes']['added']} should be 0"
    )
    assert second["writes"]["changed"] == 0, (
        f"second run changed={second['writes']['changed']} should be 0"
    )
    assert second["writes"]["removed"] == 0, (
        f"second run removed={second['writes']['removed']} should be 0"
    )
    assert second["writes"]["unchanged"] == EXPECTED_TOTAL_ENTRIES


async def test_no_phantom_changes_from_order():
    """Worker processing order does not produce phantom changes.

    Runs scan with concurrency=1 (serial) and concurrency=16 (parallel),
    then verifies both produce identical entry sets, order, and metadata.
    """
    provider_serial = FakeAListProvider(_make_big_tree())
    adapter_serial = AListProviderAdapter(provider_serial, [_make_root()])
    entries_serial, _, complete_serial = await adapter_serial.scan_category(
        "root:1", concurrency=1
    )

    provider_parallel = FakeAListProvider(_make_big_tree())
    adapter_parallel = AListProviderAdapter(provider_parallel, [_make_root()])
    entries_parallel, _, complete_parallel = await adapter_parallel.scan_category(
        "root:1", concurrency=16
    )

    assert complete_serial is True
    assert complete_parallel is True

    assert _entry_paths(entries_serial) == _entry_paths(entries_parallel)
    assert _entry_ids(entries_serial) == _entry_ids(entries_parallel)
    assert [e.path for e in entries_serial] == [e.path for e in entries_parallel]

    serial_by_path = {e.path: e for e in entries_serial}
    for entry in entries_parallel:
        ref = serial_by_path[entry.path]
        assert entry.resource_id == ref.resource_id
        assert entry.metadata["depth"] == ref.metadata["depth"]
        assert entry.metadata["parent_id"] == ref.metadata["parent_id"]
        assert entry.metadata["parent_path"] == ref.metadata["parent_path"]
        assert entry.metadata["child_folder_count"] == ref.metadata["child_folder_count"]
        assert entry.metadata["resource_count"] == ref.metadata["resource_count"]


class _KeyOrderVaryingProvider:
    """Provider that returns items with JSON keys in different insertion orders.

    On even-numbered list_path calls, the keys of each item dict are reversed.
    This verifies that the adapter does not depend on JSON key order.
    """

    def __init__(self, tree: dict[str, list[dict[str, Any]]]) -> None:
        self._tree = tree
        self._call_count = 0

    async def list_path(
        self,
        path: str,
        refresh: bool = False,
        strict: bool = False,
    ) -> list[dict[str, Any]]:
        self._call_count += 1
        items = self._tree.get(path, [])
        if self._call_count % 2 == 0:
            reordered = []
            for item in items:
                reordered.append({k: v for k, v in reversed(list(item.items()))})
            return reordered
        return [dict(item) for item in items]

    async def get_metadata(self, path: str) -> dict[str, Any]:
        return {"name": path.rsplit("/", 1)[-1]}


async def test_no_phantom_changes_from_json_key_order():
    """JSON key order in provider items does not produce phantom changes.

    Scans the same tree twice: once with normal key order, once with
    reversed key order on every other list_path call. Both scans must
    produce identical entries.
    """
    tree = _make_big_tree()

    provider_normal = FakeAListProvider(tree)
    adapter_normal = AListProviderAdapter(provider_normal, [_make_root()])
    entries_normal, _, complete_normal = await adapter_normal.scan_category(
        "root:1", concurrency=8
    )

    provider_varying = _KeyOrderVaryingProvider(tree)
    adapter_varying = AListProviderAdapter(provider_varying, [_make_root()])
    entries_varying, _, complete_varying = await adapter_varying.scan_category(
        "root:1", concurrency=8
    )

    assert complete_normal is True
    assert complete_varying is True

    assert [e.path for e in entries_normal] == [e.path for e in entries_varying]
    assert _entry_ids(entries_normal) == _entry_ids(entries_varying)

    normal_by_path = {e.path: e for e in entries_normal}
    for entry in entries_varying:
        ref = normal_by_path[entry.path]
        assert entry.resource_id == ref.resource_id
        assert entry.metadata["depth"] == ref.metadata["depth"]
        assert entry.metadata["parent_id"] == ref.metadata["parent_id"]
        assert entry.metadata["is_dir"] == ref.metadata["is_dir"]
        assert entry.metadata["parent_path"] == ref.metadata["parent_path"]
