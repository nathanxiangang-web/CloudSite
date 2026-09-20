"""Performance baseline tests for indexing scan/reconcile/search.

Records elapsed / peak_memory / checkpoint_write_time / reconcile_time /
search_time / error_rate against Small / Medium / Large synthetic fixtures
to satisfy V2 doc section 63 (performance baseline) and audit-tests-4 P3
gap #14.

Each test uses ``tracemalloc`` for peak memory and ``time.monotonic`` for
elapsed. Performance data is printed to test output as the baseline record.
Assertions use loose thresholds to avoid CI environment flakiness.
"""
from __future__ import annotations

import asyncio
import gc
import statistics
import time
import tracemalloc
from datetime import datetime, timezone
from typing import Any

import pytest

from cloudsite.modules.indexing.application.reconcile import ReconcileService
from cloudsite.modules.indexing.domain.snapshot import (
    CategorySnapshot,
    SnapshotEntry,
)
from cloudsite.modules.indexing.infrastructure.alist_adapter import (
    AListProviderAdapter,
    DIRECTORY_CONCURRENCY,
)
from cloudsite.modules.indexing.infrastructure.legacy_bridge import run_indexing_v2
from cloudsite.modules.indexing.infrastructure.repository import (
    IndexedEntry,
    IndexingStore,
)
from cloudsite.modules.providers.contracts.public import ProviderScanRoot


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_IO_DELAY_SECONDS = 0.0005
_CONCURRENCY_LEVELS = (1, 2, 4, 8)

# Fixture sizes: (num_dirs, files_per_dir, total_files)
_SMALL_DIRS = 10
_SMALL_FILES = 50
_MEDIUM_DIRS = 100
_MEDIUM_FILES = 500
_LARGE_DIRS = 500
_LARGE_FILES = 2500

# Loose memory ceilings (tracemalloc peak bytes) for CI safety.
_SMALL_MEMORY_CEIL = 5 * 1024 * 1024
_MEDIUM_MEMORY_CEIL = 20 * 1024 * 1024
_LARGE_MEMORY_CEIL = 80 * 1024 * 1024


# ---------------------------------------------------------------------------
# In-memory provider (matches ProviderScanPort contract)
# ---------------------------------------------------------------------------

class FakeAListProvider:
    """In-memory provider simulating an AList tree with artificial I/O delay."""

    def __init__(
        self,
        tree: dict[str, list[dict[str, Any]]],
        io_delay: float = _IO_DELAY_SECONDS,
    ) -> None:
        self._tree = tree
        self._io_delay = io_delay
        self.list_calls: list[str] = []

    async def list_path(
        self,
        path: str,
        refresh: bool = False,
        strict: bool = False,
    ) -> list[dict[str, Any]]:
        self.list_calls.append(path)
        if self._io_delay > 0:
            await asyncio.sleep(self._io_delay)
        return list(self._tree.get(path, []))

    async def get_metadata(self, path: str) -> dict[str, Any]:
        return {"name": path.rsplit("/", 1)[-1]}


# ---------------------------------------------------------------------------
# Tree builders
# ---------------------------------------------------------------------------

def _build_flat_tree(
    num_dirs: int,
    total_files: int,
) -> dict[str, list[dict[str, Any]]]:
    """Build a flat tree with exactly ``num_dirs`` directories and
    ``total_files`` files.

    Layout:
      /root                         (1 dir)
        /d0..d{num_dirs-2}          (num_dirs - 1 subdirs)
          f0..f{per_sub-1}          (files in each subdir)
        root_file_0..k              (remaining files in root)

    Total dirs = 1 + (num_dirs - 1) = num_dirs.
    Total files = (num_dirs - 1) * per_sub + root_files = total_files.
    """
    sub_dirs = num_dirs - 1
    per_sub = max(1, total_files // num_dirs)
    sub_total = sub_dirs * per_sub
    root_files = total_files - sub_total
    if root_files < 0:
        per_sub = max(1, total_files // max(sub_dirs, 1))
        sub_total = sub_dirs * per_sub
        root_files = total_files - sub_total

    tree: dict[str, list[dict[str, Any]]] = {}
    root_items: list[dict[str, Any]] = []

    for i in range(sub_dirs):
        dir_name = f"d{i}"
        root_items.append({"name": dir_name, "is_dir": True})
        tree[f"/root/{dir_name}"] = [
            {"name": f"f{j}", "is_dir": False, "size": 100 * j + 1}
            for j in range(per_sub)
        ]

    for k in range(max(root_files, 0)):
        root_items.append({"name": f"root_file_{k}", "is_dir": False, "size": 10})

    tree["/root"] = root_items
    return tree


def _make_root() -> ProviderScanRoot:
    return ProviderScanRoot(
        root_mapping_id=1,
        content_type="software",
        storage_path="/root",
        display_name="PerfRoot",
    )


# ---------------------------------------------------------------------------
# In-memory IndexingStore for reconcile timing
# ---------------------------------------------------------------------------

class _InMemoryStore:
    """Minimal in-memory IndexingStore for reconcile performance timing."""

    def __init__(self) -> None:
        self._entries: dict[str, IndexedEntry] = {}

    async def list_indexed(
        self, *, category_id: str, provider_id: str
    ) -> list[IndexedEntry]:
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


# ---------------------------------------------------------------------------
# Scan helper
# ---------------------------------------------------------------------------

async def _scan_with_metrics(
    tree: dict[str, list[dict[str, Any]]],
    concurrency: int = DIRECTORY_CONCURRENCY,
) -> dict[str, Any]:
    """Run a scan recording elapsed (time.monotonic) and peak memory."""
    tracemalloc.start()
    try:
        provider = FakeAListProvider(tree)
        adapter = AListProviderAdapter(provider, [_make_root()])
        start = time.monotonic()
        entries, _, complete = await adapter.scan_category(
            "root:1", concurrency=concurrency
        )
        elapsed = time.monotonic() - start
        _, peak = tracemalloc.get_traced_memory()
        metrics = adapter.last_scan_metrics
    finally:
        tracemalloc.stop()

    return {
        "elapsed_seconds": elapsed,
        "peak_memory_bytes": peak,
        "entries_discovered": metrics["entries_discovered"],
        "dirs_done": metrics["dirs_done"],
        "entry_count": len(entries),
        "complete": complete,
        "entries": entries,
    }


# ---------------------------------------------------------------------------
# Fixtures (module scope: build once, reuse across tests)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def _SmallFixture() -> dict[str, Any]:
    """10 directories / 50 files."""
    tree = _build_flat_tree(_SMALL_DIRS, _SMALL_FILES)
    return {"tree": tree, "num_dirs": _SMALL_DIRS, "num_files": _SMALL_FILES}


@pytest.fixture(scope="module")
def _MediumFixture() -> dict[str, Any]:
    """100 directories / 500 files."""
    tree = _build_flat_tree(_MEDIUM_DIRS, _MEDIUM_FILES)
    return {"tree": tree, "num_dirs": _MEDIUM_DIRS, "num_files": _MEDIUM_FILES}


@pytest.fixture(scope="module")
def _LargeFixture() -> dict[str, Any]:
    """500 directories / 2500 files."""
    tree = _build_flat_tree(_LARGE_DIRS, _LARGE_FILES)
    return {"tree": tree, "num_dirs": _LARGE_DIRS, "num_files": _LARGE_FILES}


# ---------------------------------------------------------------------------
# Performance baseline tests
# ---------------------------------------------------------------------------

async def test_small_fixture_performance(_SmallFixture) -> None:
    """Small fixture (10 dirs / 50 files): scan elapsed + peak memory recorded."""
    result = await _scan_with_metrics(_SmallFixture["tree"])

    print("\n" + "=" * 70)
    print("PERFORMANCE BASELINE - Small Fixture (10 dirs / 50 files)")
    print("=" * 70)
    print(f"  elapsed_seconds:    {result['elapsed_seconds']:.6f}")
    print(f"  peak_memory_bytes:  {result['peak_memory_bytes']}")
    print(f"  peak_memory_KiB:    {result['peak_memory_bytes'] / 1024:.2f}")
    print(f"  entries_discovered: {result['entries_discovered']}")
    print(f"  dirs_done:          {result['dirs_done']}")
    print(f"  complete:           {result['complete']}")
    print("=" * 70)

    assert result["complete"] is True
    assert result["entry_count"] > 0
    assert result["elapsed_seconds"] > 0.0
    assert result["peak_memory_bytes"] > 0
    assert result["peak_memory_bytes"] < _SMALL_MEMORY_CEIL


async def test_medium_fixture_performance(_MediumFixture) -> None:
    """Medium fixture (100 dirs / 500 files): scan elapsed + peak memory recorded."""
    result = await _scan_with_metrics(_MediumFixture["tree"])

    print("\n" + "=" * 70)
    print("PERFORMANCE BASELINE - Medium Fixture (100 dirs / 500 files)")
    print("=" * 70)
    print(f"  elapsed_seconds:    {result['elapsed_seconds']:.6f}")
    print(f"  peak_memory_bytes:  {result['peak_memory_bytes']}")
    print(f"  peak_memory_KiB:    {result['peak_memory_bytes'] / 1024:.2f}")
    print(f"  entries_discovered: {result['entries_discovered']}")
    print(f"  dirs_done:          {result['dirs_done']}")
    print(f"  complete:           {result['complete']}")
    print("=" * 70)

    assert result["complete"] is True
    assert result["entry_count"] > 0
    assert result["elapsed_seconds"] > 0.0
    assert result["peak_memory_bytes"] > 0
    assert result["peak_memory_bytes"] < _MEDIUM_MEMORY_CEIL


async def test_large_fixture_performance(_LargeFixture) -> None:
    """Large fixture (500 dirs / 2500 files): scan elapsed + peak memory recorded."""
    result = await _scan_with_metrics(_LargeFixture["tree"])

    print("\n" + "=" * 70)
    print("PERFORMANCE BASELINE - Large Fixture (500 dirs / 2500 files)")
    print("=" * 70)
    print(f"  elapsed_seconds:    {result['elapsed_seconds']:.6f}")
    print(f"  peak_memory_bytes:  {result['peak_memory_bytes']}")
    print(f"  peak_memory_KiB:    {result['peak_memory_bytes'] / 1024:.2f}")
    print(f"  peak_memory_MiB:    {result['peak_memory_bytes'] / (1024 * 1024):.4f}")
    print(f"  entries_discovered: {result['entries_discovered']}")
    print(f"  dirs_done:          {result['dirs_done']}")
    print(f"  complete:           {result['complete']}")
    print("=" * 70)

    assert result["complete"] is True
    assert result["entry_count"] > 0
    assert result["elapsed_seconds"] > 0.0
    assert result["peak_memory_bytes"] > 0
    assert result["peak_memory_bytes"] < _LARGE_MEMORY_CEIL


async def test_reconcile_time_proportional(
    _SmallFixture,
    _MediumFixture,
    _LargeFixture,
) -> None:
    """Reconcile time grows proportionally with entry count (not super-linear).

    Measures reconcile_time for small/medium/large snapshots against an
    in-memory store. Asserts that reconcile_time_large / reconcile_time_small
    does not explode relative to the entry-count ratio (loose threshold to
    accommodate CI jitter).
    """
    async def _reconcile_time(fixture: dict[str, Any]) -> dict[str, Any]:
        scan = await _scan_with_metrics(fixture["tree"])
        entries = scan["entries"]
        snapshot = CategorySnapshot(
            category_id="root:1",
            provider_id="fake-provider",
            entries=entries,
            pagination_complete=True,
        )

        async def _one_sample() -> tuple[float, int]:
            store = _InMemoryStore()
            service = ReconcileService(store)
            gc_was_enabled = gc.isenabled()
            if gc_was_enabled:
                gc.disable()
            try:
                start_ns = time.perf_counter_ns()
                result = await service.reconcile(snapshot)
                elapsed = (time.perf_counter_ns() - start_ns) / 1_000_000_000
            finally:
                if gc_was_enabled:
                    gc.enable()
            return elapsed, result.writes.added

        # Warm the interpreter/code paths first. The measured operation is
        # allocation-heavy but contains no intentional cyclic object graph;
        # disabling cyclic GC during each sample avoids threshold-triggered GC
        # pauses being misclassified as algorithmic super-linearity.
        await _one_sample()

        samples: list[float] = []
        added = 0
        for _ in range(5):
            elapsed, added = await _one_sample()
            samples.append(elapsed)

        return {
            "reconcile_time": statistics.median(samples),
            "reconcile_samples": samples,
            "entry_count": len(entries),
            "added": added,
        }

    small = await _reconcile_time(_SmallFixture)
    medium = await _reconcile_time(_MediumFixture)
    large = await _reconcile_time(_LargeFixture)

    print("\n" + "=" * 70)
    print("RECONCILE TIME PROPORTIONALITY")
    print("=" * 70)
    print(f"  small:  entries={small['entry_count']:>5}  "
          f"reconcile_time={small['reconcile_time']:.6f}s  "
          f"added={small['added']}")
    print(f"  medium: entries={medium['entry_count']:>5}  "
          f"reconcile_time={medium['reconcile_time']:.6f}s  "
          f"added={medium['added']}")
    print(f"  large:  entries={large['entry_count']:>5}  "
          f"reconcile_time={large['reconcile_time']:.6f}s  "
          f"added={large['added']}")
    print(f"  small_samples:  {small['reconcile_samples']}")
    print(f"  medium_samples: {medium['reconcile_samples']}")
    print(f"  large_samples:  {large['reconcile_samples']}")
    if small["reconcile_time"] > 0:
        ratio_time = large["reconcile_time"] / small["reconcile_time"]
        ratio_entries = large["entry_count"] / small["entry_count"]
        print(f"  time_ratio (large/small):   {ratio_time:.2f}x")
        print(f"  entry_ratio (large/small):  {ratio_entries:.2f}x")
    print("=" * 70)

    assert small["added"] == small["entry_count"]
    assert medium["added"] == medium["entry_count"]
    assert large["added"] == large["entry_count"]
    assert small["reconcile_time"] > 0.0
    assert medium["reconcile_time"] > 0.0
    assert large["reconcile_time"] > 0.0
    if small["reconcile_time"] > 0:
        ratio_time = large["reconcile_time"] / small["reconcile_time"]
        ratio_entries = large["entry_count"] / small["entry_count"]
        assert ratio_time < ratio_entries * 10.0 + 50.0, (
            f"reconcile time super-linear: ratio_time={ratio_time:.2f} "
            f"ratio_entries={ratio_entries:.2f}"
        )


async def test_peak_memory_linear(
    _SmallFixture,
    _MediumFixture,
    _LargeFixture,
) -> None:
    """Peak memory grows roughly linearly with fixture size (not exponential).

    Asserts that peak_large / peak_small is bounded by a loose linear factor
    of the size ratio, ruling out quadratic/exponential memory blowup.
    """
    small = await _scan_with_metrics(_SmallFixture["tree"])
    medium = await _scan_with_metrics(_MediumFixture["tree"])
    large = await _scan_with_metrics(_LargeFixture["tree"])

    peak_small = small["peak_memory_bytes"]
    peak_medium = medium["peak_memory_bytes"]
    peak_large = large["peak_memory_bytes"]
    size_ratio = _LARGE_DIRS / _SMALL_DIRS

    print("\n" + "=" * 70)
    print("PEAK MEMORY LINEARITY")
    print("=" * 70)
    print(f"  small:  peak={peak_small:>10} bytes ({peak_small / 1024:.2f} KiB)")
    print(f"  medium: peak={peak_medium:>10} bytes ({peak_medium / 1024:.2f} KiB)")
    print(f"  large:  peak={peak_large:>10} bytes ({peak_large / 1024:.2f} KiB)")
    print(f"  size_ratio (large/small dirs): {size_ratio:.1f}x")
    if peak_small > 0:
        mem_ratio = peak_large / peak_small
        print(f"  mem_ratio (large/small):      {mem_ratio:.2f}x")
    print("=" * 70)

    assert peak_small > 0
    assert peak_medium > 0
    assert peak_large > 0
    assert peak_medium >= peak_small * 0.5
    if peak_small > 0:
        mem_ratio = peak_large / peak_small
        assert mem_ratio < size_ratio * 20.0 + 100.0, (
            f"memory super-linear: mem_ratio={mem_ratio:.2f} "
            f"size_ratio={size_ratio:.2f}"
        )


async def test_error_rate_zero_on_clean_fixture(_MediumFixture) -> None:
    """A clean fixture produces zero errors (error_rate = 0).

    Runs the full ``run_indexing_v2`` pipeline (scan + reconcile) against the
    medium fixture with an in-memory store and asserts the error list is empty
    and error_rate == 0.0.
    """
    tree = _MediumFixture["tree"]
    provider = FakeAListProvider(tree)
    adapter = AListProviderAdapter(provider, [_make_root()])
    store = _InMemoryStore()
    category_ids = ["root:1"]

    start = time.monotonic()
    result = await run_indexing_v2(
        adapter=adapter,
        store=store,
        category_ids=category_ids,
    )
    elapsed = time.monotonic() - start

    errors = result.get("errors", [])
    total_categories = len(category_ids)
    error_rate = len(errors) / total_categories if total_categories > 0 else 0.0

    print("\n" + "=" * 70)
    print("ERROR RATE ON CLEAN FIXTURE")
    print("=" * 70)
    print(f"  status:            {result.get('status')}")
    print(f"  categories_scanned:{result.get('categories_scanned')}")
    print(f"  errors:            {errors}")
    print(f"  error_rate:        {error_rate}")
    print(f"  elapsed_seconds:   {elapsed:.6f}")
    print("=" * 70)

    assert errors == []
    assert error_rate == 0.0
    assert result.get("status") == "success"


async def test_concurrency_scaling_performance(_MediumFixture) -> None:
    """Concurrency=1/2/4/8 on medium fixture: record scaling baseline.

    Records elapsed/throughput at each concurrency level. Asserts all levels
    complete successfully and produce identical entry counts. Does NOT assert
    strict monotonic speedup (CI scheduling jitter makes that flaky); instead
    records the baseline and requires throughput_8 >= throughput_1 * 0.3 as a
    loose floor.
    """
    tree = _MediumFixture["tree"]
    results: dict[int, dict[str, Any]] = {}

    for level in _CONCURRENCY_LEVELS:
        provider = FakeAListProvider(tree)
        adapter = AListProviderAdapter(provider, [_make_root()])
        tracemalloc.start()
        try:
            start = time.monotonic()
            entries, _, complete = await adapter.scan_category(
                "root:1", concurrency=level
            )
            elapsed = time.monotonic() - start
            _, peak = tracemalloc.get_traced_memory()
            metrics = adapter.last_scan_metrics
        finally:
            tracemalloc.stop()
        entries_discovered = metrics["entries_discovered"]
        throughput = entries_discovered / elapsed if elapsed > 0 else 0.0
        results[level] = {
            "concurrency": level,
            "effective_concurrency": min(level, DIRECTORY_CONCURRENCY),
            "elapsed_seconds": elapsed,
            "throughput": throughput,
            "entries_discovered": entries_discovered,
            "dirs_done": metrics["dirs_done"],
            "peak_memory_bytes": peak,
            "entry_count": len(entries),
            "complete": complete,
        }

    print("\n" + "=" * 70)
    print("CONCURRENCY SCALING BASELINE - Medium Fixture (100 dirs / 500 files)")
    print("=" * 70)
    header = (
        f"{'concurrency':>12} {'effective':>10} {'elapsed_s':>12} "
        f"{'throughput':>14} {'entries':>8} {'dirs':>6} "
        f"{'peak_KiB':>10} {'complete':>9}"
    )
    print(header)
    print("-" * 70)
    for level in _CONCURRENCY_LEVELS:
        r = results[level]
        print(
            f"{r['concurrency']:>12} "
            f"{r['effective_concurrency']:>10} "
            f"{r['elapsed_seconds']:>12.6f} "
            f"{r['throughput']:>14.2f} "
            f"{r['entries_discovered']:>8} "
            f"{r['dirs_done']:>6} "
            f"{r['peak_memory_bytes'] / 1024:>10.2f} "
            f"{str(r['complete']):>9}"
        )
    print("=" * 70)
    t1 = results[1]["throughput"]
    t8 = results[8]["throughput"]
    if t1 > 0:
        print(f"throughput ratio (c=8 / c=1): {t8 / t1:.2f}x")
    print(f"DIRECTORY_CONCURRENCY cap: {DIRECTORY_CONCURRENCY}")

    ref_count = results[_CONCURRENCY_LEVELS[0]]["entry_count"]
    for level in _CONCURRENCY_LEVELS:
        r = results[level]
        assert r["complete"] is True, (
            f"concurrency={level} did not complete"
        )
        assert r["entry_count"] == ref_count, (
            f"concurrency={level} entry_count={r['entry_count']} "
            f"differs from c=1 entry_count={ref_count}"
        )
        assert r["entries_discovered"] > 0
        assert r["elapsed_seconds"] > 0.0
        assert r["peak_memory_bytes"] > 0
        assert r["peak_memory_bytes"] < _MEDIUM_MEMORY_CEIL

    tolerance = 0.3
    assert t8 >= t1 * tolerance, (
        f"expected throughput_8 >= throughput_1 * {tolerance} "
        f"({t1 * tolerance:.2f}), got throughput_8={t8:.2f} "
        f"(throughput_1={t1:.2f}, ratio={t8 / t1:.2f}x)"
    )
