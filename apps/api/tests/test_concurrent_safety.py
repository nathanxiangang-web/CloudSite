"""R1 concurrent safety property tests.

Verifies safety properties under concurrent scanning per V2 doc section 54 and
audit-tests-4 P2 gap item 9:
- SQLite concurrent safety (no unhandled locks, serial reconcile writes)
- Memory safety (bounded memory under concurrency)
- Error isolation (worker errors do not kill others, CancelledError propagates)
- Queue safety (complete drain, no sentinel leak)
"""
from __future__ import annotations

import asyncio
import tracemalloc
from datetime import datetime, timezone
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.alist import AListError
from cloudsite.modules.indexing.domain.inspection import (
    InspectionRequest,
    InspectionResult,
)
from cloudsite.modules.indexing.domain.snapshot import SnapshotEntry
from cloudsite.modules.indexing.infrastructure.alist_adapter import (
    AListProviderAdapter,
    DIRECTORY_CONCURRENCY,
)
from cloudsite.modules.indexing.infrastructure.legacy_bridge import (
    GLOBAL_SCAN_CONCURRENCY,
    RECONCILE_CONCURRENCY,
    run_indexing_v2,
)
from cloudsite.modules.indexing.infrastructure.provider_adapter import (
    ProviderCapabilities,
)
from cloudsite.modules.indexing.infrastructure.repository import (
    IndexedEntry,
    IndexingRepository,
    ResourceSkeletonORM,
)
from cloudsite.modules.providers.contracts.public import ProviderScanRoot
from cloudsite.platform.db.base import StateBase


# ---------------------------------------------------------------------------
# Shared helpers
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


def _snapshot_entry(
    rid: str,
    path: str,
    name: str,
    is_dir: bool = False,
    root_mapping_id: int = 1,
) -> SnapshotEntry:
    return SnapshotEntry(
        resource_id=rid,
        path=path,
        name=name,
        size=100 if not is_dir else None,
        modified_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        content_hash="h",
        metadata={
            "is_dir": is_dir,
            "content_type": "software",
            "root_mapping_id": root_mapping_id,
            "depth": 0,
            "child_folder_count": 0,
            "resource_count": 0,
            "parent_path": None,
            "parent_id": None,
            "extension": "",
            "mime_type": "application/octet-stream",
            "thumbnail": "",
        },
    )


class _CatalogAdapter:
    """Provider adapter backed by a category-id -> entries catalog."""

    def __init__(self, catalog: dict[str, list[SnapshotEntry]]) -> None:
        self._catalog = catalog
        self.last_scan_metrics: dict[str, int] = {
            "active_workers": 0,
            "dirs_done": 0,
            "dirs_pending": 0,
            "entries_discovered": 0,
        }

    @property
    def provider_id(self) -> str:
        return "fake-provider"

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
    ) -> tuple[list[SnapshotEntry], str | None, bool]:
        entries = list(self._catalog.get(category_id, []))
        self.last_scan_metrics = {
            "active_workers": 0,
            "dirs_done": 1,
            "dirs_pending": 0,
            "entries_discovered": len(entries),
        }
        return entries, None, True

    async def inspect(self, request: InspectionRequest) -> InspectionResult:
        return InspectionResult(
            resource_id=request.resource_id,
            provider_id=request.provider_id,
            path="",
            name="",
        )


def _build_catalog(category_ids: list[str]) -> dict[str, list[SnapshotEntry]]:
    return {
        cid: [
            _snapshot_entry(f"{cid}-folder", f"/{cid}", "root", is_dir=True),
            _snapshot_entry(f"{cid}-file1", f"/{cid}/f1", "f1"),
            _snapshot_entry(f"{cid}-file2", f"/{cid}/f2", "f2"),
        ]
        for cid in category_ids
    }


# ---------------------------------------------------------------------------
# SQLite concurrent safety
# ---------------------------------------------------------------------------

async def test_no_unhandled_sqlite_lock(tmp_path) -> None:
    """Concurrent scan + serial reconcile produces no unhandled SQLite lock errors."""
    db_path = tmp_path / "test_concurrent_index.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    category_ids = [f"root:{i}" for i in range(1, 5)]
    catalog = _build_catalog(category_ids)
    adapter = _CatalogAdapter(catalog)

    async with session_factory() as session:
        store = IndexingRepository(session)
        result = await run_indexing_v2(
            adapter=adapter,
            store=store,
            category_ids=category_ids,
        )
        await session.commit()

    assert result["status"] == "success"
    assert result["errors"] == []
    assert result["categories_scanned"] == 4
    assert result["writes"]["added"] == 12

    for error in result.get("errors", []):
        assert "locked" not in error.lower()
        assert "database is locked" not in error.lower()

    async with session_factory() as session:
        res = await session.execute(select(ResourceSkeletonORM))
        rows = res.scalars().all()
        assert len(rows) == 12

    await engine.dispose()


class _ConcurrentWriteTrackingStore:
    """In-memory store that tracks the peak number of concurrent write calls."""

    def __init__(self) -> None:
        self._entries: dict[str, IndexedEntry] = {}
        self._live_writes = 0
        self.max_concurrent_writes = 0
        self._lock = asyncio.Lock()

    async def list_indexed(
        self, *, category_id: str, provider_id: str
    ) -> list[IndexedEntry]:
        return [
            e for e in self._entries.values()
            if e.category_id == category_id and e.provider_id == provider_id
        ]

    async def upsert(self, entries: list[IndexedEntry]) -> int:
        async with self._lock:
            self._live_writes += 1
            self.max_concurrent_writes = max(
                self.max_concurrent_writes, self._live_writes
            )
        await asyncio.sleep(0.01)
        for e in entries:
            self._entries[e.resource_id] = e
        async with self._lock:
            self._live_writes -= 1
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


async def test_reconcile_no_concurrent_writes() -> None:
    """Reconcile phase has no concurrent writes (RECONCILE_CONCURRENCY=1 in effect)."""
    assert RECONCILE_CONCURRENCY == 1

    category_ids = [f"root:{i}" for i in range(1, 5)]
    catalog = _build_catalog(category_ids)
    adapter = _CatalogAdapter(catalog)
    store = _ConcurrentWriteTrackingStore()

    await run_indexing_v2(
        adapter=adapter,
        store=store,
        category_ids=category_ids,
    )

    assert store.max_concurrent_writes <= 1, (
        f"reconcile must be serial but max_concurrent_writes="
        f"{store.max_concurrent_writes}"
    )


# ---------------------------------------------------------------------------
# Memory safety
# ---------------------------------------------------------------------------

async def test_no_excessive_memory_under_concurrency() -> None:
    """Concurrency=16 (capped to DIRECTORY_CONCURRENCY=8) keeps memory bounded."""
    tree = _make_tree()

    tracemalloc.start()
    try:
        provider = FakeProvider(tree)
        adapter = AListProviderAdapter(provider, [_make_root()])
        entries, _, complete = await adapter.scan_category(
            "root:1", concurrency=16
        )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert complete is True
    assert _entry_paths(entries) == EXPECTED_PATHS
    assert peak < 10 * 1024 * 1024


def _make_large_tree(
    num_dirs: int = 50, files_per_dir: int = 10
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


async def test_entries_not_held_in_memory_simultaneously() -> None:
    """Large directory tree scan keeps memory controlled (linear, not explosive)."""
    num_dirs = 50
    files_per_dir = 10
    tree = _make_large_tree(num_dirs, files_per_dir)
    expected_count = 1 + num_dirs + num_dirs * files_per_dir

    tracemalloc.start()
    try:
        provider = FakeProvider(tree)
        adapter = AListProviderAdapter(provider, [_make_root()])
        entries, _, complete = await adapter.scan_category(
            "root:1", concurrency=8
        )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert complete is True
    assert len(entries) == expected_count
    assert peak < 50 * 1024 * 1024
    per_entry = peak / expected_count
    assert per_entry < 10 * 1024


# ---------------------------------------------------------------------------
# Error isolation
# ---------------------------------------------------------------------------

async def test_one_worker_error_does_not_kill_others() -> None:
    """An AListError in one worker does not interrupt other workers."""

    class ErrorOnBProvider(FakeProvider):
        async def list_path(self, path: str, refresh=False, strict=False):
            if path == "/root/b":
                raise AListError("boom", "AL-500")
            return await super().list_path(
                path, refresh=refresh, strict=strict
            )

    provider = ErrorOnBProvider(_make_tree())
    adapter = AListProviderAdapter(provider, [_make_root()])
    entries, _, complete = await adapter.scan_category("root:1", concurrency=8)

    assert "/root/b/b1" not in _entry_paths(entries)
    assert "/root/b" in _entry_paths(entries)
    assert "/root/a/a1" in _entry_paths(entries)
    assert "/root/a/a2" in _entry_paths(entries)
    assert "/root/a/sub/deep.zip" in _entry_paths(entries)
    assert "/root/c" in _entry_paths(entries)
    assert complete is False


async def test_cancelled_error_propagates() -> None:
    """CancelledError propagates correctly and is not swallowed by the scanner."""

    class SlowProvider(FakeProvider):
        async def list_path(self, path: str, refresh=False, strict=False):
            await asyncio.sleep(0.1)
            return await super().list_path(
                path, refresh=refresh, strict=strict
            )

    provider = SlowProvider(_make_tree())
    adapter = AListProviderAdapter(provider, [_make_root()])
    task = asyncio.create_task(adapter.scan_category("root:1", concurrency=8))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_partial_scan_metrics_correct() -> None:
    """Partial scan metrics correctly reflect completed vs uncompleted work."""

    class ErrorOnBProvider(FakeProvider):
        async def list_path(self, path: str, refresh=False, strict=False):
            if path == "/root/b":
                raise AListError("boom", "AL-500")
            return await super().list_path(
                path, refresh=refresh, strict=strict
            )

    provider = ErrorOnBProvider(_make_tree())
    adapter = AListProviderAdapter(provider, [_make_root()])
    entries, _, complete = await adapter.scan_category("root:1", concurrency=8)
    metrics = adapter.last_scan_metrics

    assert metrics["dirs_done"] == len(EXPECTED_DIRS)
    assert metrics["entries_discovered"] == len(entries)
    assert metrics["entries_discovered"] == len(EXPECTED_PATHS) - 1
    assert metrics["active_workers"] == 0
    assert metrics["dirs_pending"] == 0
    assert complete is False


# ---------------------------------------------------------------------------
# Queue safety
# ---------------------------------------------------------------------------

async def test_queue_drains_completely() -> None:
    """All directories are processed and the queue drains completely."""
    provider = FakeProvider(_make_tree())
    adapter = AListProviderAdapter(provider, [_make_root()])
    entries, _, _ = await adapter.scan_category("root:1", concurrency=8)

    assert set(provider.list_calls) == EXPECTED_DIRS
    assert _entry_paths(entries) == EXPECTED_PATHS


async def test_no_sentinel_leak() -> None:
    """Sentinel value (None) does not appear in any scan results."""
    provider = FakeProvider(_make_tree())
    adapter = AListProviderAdapter(provider, [_make_root()])
    entries, _, _ = await adapter.scan_category("root:1", concurrency=8)

    assert all(e is not None for e in entries)
    assert all(e.path is not None for e in entries)
    assert all(e.resource_id is not None for e in entries)
    assert all(p is not None for p in provider.list_calls)
    assert all(isinstance(p, str) for p in provider.list_calls)
    metrics = adapter.last_scan_metrics
    assert all(v is not None for v in metrics.values())
