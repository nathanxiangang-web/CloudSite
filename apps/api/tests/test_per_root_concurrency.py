"""R1 PR 06: per-root concurrent scan + serial reconcile regression tests.

run_indexing_v2 now runs all category scans concurrently under a global
asyncio.Semaphore(GLOBAL_SCAN_CONCURRENCY) and then reconciles serially in
sorted category_id order. These tests verify:

- multi-root concurrent scan produces the same result as serial execution
- reconcile still runs serially (no concurrent store writes)
- the semaphore caps the live scan concurrency at GLOBAL_SCAN_CONCURRENCY
- a single root scan failure does not affect other roots
- two identical runs produce byte-identical summaries (deterministic order)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from cloudsite.modules.indexing.domain.inspection import (
    InspectionRequest,
    InspectionResult,
)
from cloudsite.modules.indexing.domain.snapshot import SnapshotEntry
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
)


def _entry(rid: str, name: str = "f") -> SnapshotEntry:
    return SnapshotEntry(
        resource_id=rid,
        path=f"/{name}",
        name=name,
        size=100,
        modified_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        content_hash="h",
    )


class _ConcurrencyTrackingAdapter:
    """Provider adapter that records live scan concurrency and per-call order."""

    def __init__(self, catalog: dict[str, list[SnapshotEntry]]) -> None:
        self._catalog = catalog
        self.scan_calls: list[str] = []
        self._live = 0
        self.max_live: int = 0
        self._lock = asyncio.Lock()

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
        on_progress=None,
    ) -> tuple[list[SnapshotEntry], str | None, bool]:
        async with self._lock:
            self._live += 1
            self.max_live = max(self.max_live, self._live)
            self.scan_calls.append(category_id)
        await asyncio.sleep(0.01)
        async with self._lock:
            self._live -= 1
        return list(self._catalog.get(category_id, [])), None, True

    async def inspect(self, request: InspectionRequest) -> InspectionResult:
        return InspectionResult(
            resource_id=request.resource_id,
            provider_id=request.provider_id,
            path="",
            name="",
        )


class _SerialReconcileStore:
    """In-memory store that asserts reconcile is never invoked concurrently."""

    def __init__(self, seeded: list[IndexedEntry] | None = None) -> None:
        self._entries: dict[str, IndexedEntry] = {
            e.resource_id: e for e in (seeded or [])
        }
        self._live = 0
        self.max_live: int = 0
        self.reconcile_calls: list[str] = []
        self.upsert_calls: int = 0
        self.remove_calls: int = 0

    async def list_indexed(self, *, category_id: str, provider_id: str) -> list[IndexedEntry]:
        self._live += 1
        self.max_live = max(self.max_live, self._live)
        self.reconcile_calls.append(category_id)
        await asyncio.sleep(0.01)
        self._live -= 1
        return [
            e for e in self._entries.values()
            if e.category_id == category_id and e.provider_id == provider_id
        ]

    async def upsert(self, entries: list[IndexedEntry]) -> int:
        for e in entries:
            self._entries[e.resource_id] = e
        self.upsert_calls += 1
        return len(entries)

    async def remove(self, resource_ids: list[str]) -> int:
        removed = 0
        for rid in resource_ids:
            if rid in self._entries:
                del self._entries[rid]
                removed += 1
        self.remove_calls += 1
        return removed

    async def touch_unchanged(self, resource_ids: list[str]) -> int:
        return len(resource_ids)


def _build_catalog(category_ids: list[str]) -> dict[str, list[SnapshotEntry]]:
    return {
        cid: [_entry(f"{cid}-r1", "f1"), _entry(f"{cid}-r2", "f2")]
        for cid in category_ids
    }


async def test_multi_root_concurrent_scan() -> None:
    """Concurrent scan produces the same aggregate result as serial execution."""
    category_ids = ["root:1", "root:2", "root:3", "root:4"]
    catalog = _build_catalog(category_ids)

    concurrent_adapter = _ConcurrencyTrackingAdapter(catalog)
    concurrent_store = _SerialReconcileStore()
    concurrent_result = await run_indexing_v2(
        adapter=concurrent_adapter,
        store=concurrent_store,
        category_ids=category_ids,
    )

    serial_adapter = _ConcurrencyTrackingAdapter(catalog)
    serial_store = _SerialReconcileStore()
    serial_result = await run_indexing_v2(
        adapter=serial_adapter,
        store=serial_store,
        category_ids=category_ids,
    )

    assert concurrent_result == serial_result
    assert concurrent_result["status"] == "success"
    assert concurrent_result["categories_scanned"] == 4
    assert concurrent_result["writes"]["added"] == 8
    assert concurrent_adapter.max_live >= 2, "scans must run concurrently"


async def test_reconcile_serial() -> None:
    """Reconcile must never execute concurrently (max live reconcile == 1)."""
    category_ids = ["root:1", "root:2", "root:3", "root:4"]
    adapter = _ConcurrencyTrackingAdapter(_build_catalog(category_ids))
    store = _SerialReconcileStore()

    await run_indexing_v2(
        adapter=adapter,
        store=store,
        category_ids=category_ids,
    )

    assert store.max_live == 1, (
        f"reconcile must be serial but max_live={store.max_live}"
    )
    assert store.reconcile_calls == sorted(category_ids), (
        "reconcile must run in sorted category_id order"
    )


async def test_semaphore_limits_concurrency() -> None:
    """Live scan concurrency must never exceed GLOBAL_SCAN_CONCURRENCY."""
    category_count = GLOBAL_SCAN_CONCURRENCY * 3
    category_ids = [f"root:{i}" for i in range(category_count)]
    adapter = _ConcurrencyTrackingAdapter(_build_catalog(category_ids))
    store = _SerialReconcileStore()

    await run_indexing_v2(
        adapter=adapter,
        store=store,
        category_ids=category_ids,
    )

    assert adapter.max_live <= GLOBAL_SCAN_CONCURRENCY, (
        f"max_live={adapter.max_live} exceeded semaphore={GLOBAL_SCAN_CONCURRENCY}"
    )
    assert adapter.max_live == GLOBAL_SCAN_CONCURRENCY, (
        f"semaphore should allow up to {GLOBAL_SCAN_CONCURRENCY} concurrent scans, "
        f"observed max_live={adapter.max_live}"
    )


async def test_partial_root_no_commit() -> None:
    """A failing root scan must not affect other roots' results."""
    catalog = _build_catalog(["root:good-1", "root:good-2"])

    class ExplodingAdapter(_ConcurrencyTrackingAdapter):
        async def scan_category(self, category_id, *, cursor=None, limit=None, on_progress=None):
            if category_id == "root:bad":
                raise RuntimeError("boom")
            return await super().scan_category(
                category_id, cursor=cursor, limit=limit, on_progress=on_progress,
            )

    adapter = ExplodingAdapter({**catalog, "root:bad": []})
    store = _SerialReconcileStore()

    result = await run_indexing_v2(
        adapter=adapter,
        store=store,
        category_ids=["root:bad", "root:good-1", "root:good-2"],
    )

    assert result["status"] == "partial"
    assert result["categories_scanned"] == 2
    assert len(result["errors"]) == 1
    assert "root:bad" in result["errors"][0]
    assert "RuntimeError" in result["errors"][0]
    assert result["writes"]["added"] == 4


async def test_deterministic_order() -> None:
    """Two identical runs must produce byte-identical result dicts."""
    category_ids = ["root:z", "root:a", "root:m", "root:b"]
    catalog = _build_catalog(category_ids)

    result_one = await run_indexing_v2(
        adapter=_ConcurrencyTrackingAdapter(catalog),
        store=_SerialReconcileStore(),
        category_ids=category_ids,
    )
    result_two = await run_indexing_v2(
        adapter=_ConcurrencyTrackingAdapter(catalog),
        store=_SerialReconcileStore(),
        category_ids=category_ids,
    )

    assert result_one == result_two


async def test_deterministic_order_with_mixed_errors() -> None:
    """Errors and successes interleave deterministically by sorted category_id."""
    catalog = _build_catalog(["root:good-1", "root:good-2"])

    class IntermittentAdapter(_ConcurrencyTrackingAdapter):
        async def scan_category(self, category_id, *, cursor=None, limit=None, on_progress=None):
            if category_id == "root:bad":
                raise ValueError("bad data")
            return await super().scan_category(
                category_id, cursor=cursor, limit=limit, on_progress=on_progress,
            )

    full_catalog = {**catalog, "root:bad": []}
    category_ids = ["root:good-2", "root:bad", "root:good-1"]

    result_one = await run_indexing_v2(
        adapter=IntermittentAdapter(full_catalog),
        store=_SerialReconcileStore(),
        category_ids=category_ids,
    )
    result_two = await run_indexing_v2(
        adapter=IntermittentAdapter(full_catalog),
        store=_SerialReconcileStore(),
        category_ids=category_ids,
    )

    assert result_one == result_two
    assert result_one["errors"] == ["root:bad: ValueError: bad data"]
    assert result_one["categories_scanned"] == 2


def test_concurrency_constants_are_documented() -> None:
    """Sanity-check the hardcoded concurrency constants from the task spec."""
    assert GLOBAL_SCAN_CONCURRENCY == 16
    assert RECONCILE_CONCURRENCY == 1
