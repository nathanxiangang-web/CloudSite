"""Concurrent BFS scanner regression tests.

Verifies that the asyncio.Queue-based concurrent directory scanner produces
results equivalent to serial BFS, with no duplicates, no lost children, no
deadlocks, deterministic ordering, correct AListError handling, and correct
metrics counters.
"""
from __future__ import annotations

from typing import Any

import pytest

from cloudsite.modules.indexing.infrastructure.alist_adapter import (
    AListProviderAdapter,
    DIRECTORY_CONCURRENCY,
)
from cloudsite.modules.providers.contracts.public import ProviderScanRoot


class FakeProvider:
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
        return list(self._tree.get(path, []))

    async def get_metadata(self, path: str) -> dict[str, Any]:
        return {"name": path.rsplit("/", 1)[-1]}


def _make_tree() -> dict[str, list[dict[str, Any]]]:
    """Build a test tree with multiple branches and depths.

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


def _make_root() -> ProviderScanRoot:
    return ProviderScanRoot(
        root_mapping_id=1,
        content_type="software",
        storage_path="/root",
        display_name="Root",
    )


def _entry_paths(entries: list) -> set[str]:
    return {e.path for e in entries}


def _entry_ids(entries: list) -> set[str]:
    return {e.resource_id for e in entries}


EXPECTED_PATHS = {
    "/root",
    "/root/a",
    "/root/a/a1",
    "/root/a/a2",
    "/root/a/sub",
    "/root/a/sub/deep.zip",
    "/root/b",
    "/root/b/b1",
    "/root/c",
}

EXPECTED_DIRS = {
    "/root",
    "/root/a",
    "/root/a/sub",
    "/root/b",
}


async def _scan(concurrency: int) -> tuple[list, bool, dict[str, int]]:
    provider = FakeProvider(_make_tree())
    adapter = AListProviderAdapter(provider, [_make_root()])
    entries, _, complete = await adapter.scan_category(
        "root:1", concurrency=concurrency
    )
    return entries, complete, adapter.last_scan_metrics


async def test_concurrency_1_matches_serial():
    """concurrency=1 produces the same entry set as the expected serial BFS."""
    entries, complete, _ = await _scan(concurrency=1)
    assert complete is True
    assert _entry_paths(entries) == EXPECTED_PATHS
    assert len(entries) == len(EXPECTED_PATHS)


async def test_concurrency_8_matches_concurrency_1():
    """concurrency=8 produces the same entry set as concurrency=1."""
    entries_1, complete_1, _ = await _scan(concurrency=1)
    entries_8, complete_8, _ = await _scan(concurrency=8)
    assert complete_1 == complete_8
    assert _entry_ids(entries_1) == _entry_ids(entries_8)
    assert _entry_paths(entries_1) == _entry_paths(entries_8)
    assert [e.path for e in entries_1] == [e.path for e in entries_8]


async def test_no_duplicate_entries():
    """Concurrent scan produces no duplicate entries."""
    entries, _, _ = await _scan(concurrency=8)
    paths = [e.path for e in entries]
    assert len(paths) == len(set(paths))
    ids = [e.resource_id for e in entries]
    assert len(ids) == len(set(ids))


async def test_no_lost_child_dirs():
    """All child directories in the tree are discovered."""
    entries, _, _ = await _scan(concurrency=8)
    dir_paths = {e.path for e in entries if e.metadata["is_dir"]}
    assert dir_paths == EXPECTED_DIRS


async def test_no_queue_deadlock():
    """Scan completes without deadlock (returns within event loop)."""
    entries, complete, _ = await _scan(concurrency=8)
    assert len(entries) > 0
    assert complete is True


async def test_alist_error_marks_incomplete():
    """AListError during concurrent scan marks pagination_complete=False."""

    from cloudsite.alist import AListError

    class ErrorOnSubProvider(FakeProvider):
        async def list_path(self, path: str, refresh=False, strict=False):
            if path == "/root/a/sub":
                raise AListError("boom", "AL-500")
            return await super().list_path(path, refresh=refresh, strict=strict)

    provider = ErrorOnSubProvider(_make_tree())
    adapter = AListProviderAdapter(provider, [_make_root()])
    entries, _, complete = await adapter.scan_category("root:1", concurrency=8)
    assert complete is False
    assert "/root/a/sub/deep.zip" not in _entry_paths(entries)
    assert "/root/a/sub" in _entry_paths(entries)


async def test_deterministic_order():
    """Two scans with concurrency=8 produce identical entry order."""
    entries_a, _, _ = await _scan(concurrency=8)
    entries_b, _, _ = await _scan(concurrency=8)
    assert [e.path for e in entries_a] == [e.path for e in entries_b]
    assert [e.resource_id for e in entries_a] == [
        e.resource_id for e in entries_b
    ]
    assert [e.metadata["depth"] for e in entries_a] == [
        e.metadata["depth"] for e in entries_b
    ]


async def test_metrics_correct():
    """active_workers/dirs_done/dirs_pending/entries_discovered are correct."""
    entries, _, metrics = await _scan(concurrency=8)
    assert metrics["active_workers"] == 0
    assert metrics["dirs_done"] == len(EXPECTED_DIRS)
    assert metrics["dirs_pending"] == 0
    assert metrics["entries_discovered"] == len(EXPECTED_PATHS)
    assert metrics["entries_discovered"] == len(entries)


def test_directory_concurrency_constant_is_8():
    """DIRECTORY_CONCURRENCY hard cap is 8."""
    assert DIRECTORY_CONCURRENCY == 8
