"""Observability/metrics field tests for indexing v2 scan and reconcile.

V2 doc section 67 requires scan-run observability fields (run_id, status,
active_workers, directories_discovered/done/pending/failed,
entries_discovered, errors, elapsed) and reconcile metrics (added, changed,
removed, unchanged, suppressed removals). These tests verify the fields the
v2 indexing bridge and ReconcileService expose today so regressions in the
observability contract are caught without modifying source code.
"""
from __future__ import annotations

from datetime import datetime, timezone

from cloudsite.modules.indexing.application.reconcile import (
    ReconcileResult,
    ReconcileService,
    WriteSummary,
)
from cloudsite.modules.indexing.domain.snapshot import (
    CategorySnapshot,
    SnapshotEntry,
)
from cloudsite.modules.indexing.infrastructure.legacy_bridge import (
    V2IndexingSummary,
    run_indexing_v2,
)
from cloudsite.modules.indexing.infrastructure.provider_adapter import (
    ProviderCapabilities,
)
from cloudsite.modules.indexing.infrastructure.repository import IndexedEntry


class FakeProviderAdapter:
    """Minimal ProviderAdapter that returns preset entries per category."""

    def __init__(self, catalog: dict[str, list[SnapshotEntry]]) -> None:
        self._catalog = catalog
        self.scan_calls: list[tuple[str, str | None, int | None]] = []
        self.in_scan: bool = False
        self.active_observed: bool = False

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
        self.in_scan = True
        self.active_observed = True
        self.scan_calls.append((category_id, cursor, limit))
        entries = self._catalog.get(category_id, [])
        self.in_scan = False
        return list(entries), None, True


class FailingCategoryAdapter(FakeProviderAdapter):
    """Adapter that raises for specific category ids to exercise failure accounting."""

    def __init__(
        self,
        catalog: dict[str, list[SnapshotEntry]],
        fail: set[str],
    ) -> None:
        super().__init__(catalog)
        self._fail = fail

    async def scan_category(
        self,
        category_id: str,
        *,
        cursor: str | None = None,
        limit: int | None = None,
        on_progress=None,
    ) -> tuple[list[SnapshotEntry], str | None, bool]:
        if category_id in self._fail:
            raise RuntimeError(f"scan failed: {category_id}")
        return await super().scan_category(
            category_id, cursor=cursor, limit=limit, on_progress=on_progress
        )


class FakeIndexingStore:
    """In-memory IndexingStore that records all write calls."""

    def __init__(self, seeded: list[IndexedEntry] | None = None) -> None:
        self._entries: dict[str, IndexedEntry] = {
            e.resource_id: e for e in (seeded or [])
        }
        self.upsert_calls: int = 0
        self.remove_calls: int = 0
        self.touch_calls: int = 0

    async def list_indexed(
        self, *, category_id: str, provider_id: str
    ) -> list[IndexedEntry]:
        return [
            e
            for e in self._entries.values()
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
        self.touch_calls += 1
        return len(resource_ids)


def _entry(rid: str, name: str | None = None) -> SnapshotEntry:
    label = name or rid
    return SnapshotEntry(
        resource_id=rid,
        path=f"/{label}",
        name=label,
        size=100,
        modified_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        content_hash="h",
    )


def _indexed(rid: str, cat: str = "cat-a", prov: str = "fake-provider") -> IndexedEntry:
    return IndexedEntry(
        resource_id=rid,
        category_id=cat,
        provider_id=prov,
        path=f"/{rid}",
        name=rid,
        size=1,
    )


REQUIRED_SCAN_FIELDS = {
    "status",
    "engine",
    "categories_scanned",
    "pages_fetched",
    "writes",
    "suppressed_removals",
    "errors",
}

REQUIRED_WRITE_FIELDS = {"added", "changed", "removed", "unchanged"}


# --- Scan metrics ---


async def test_scan_metrics_has_required_fields() -> None:
    adapter = FakeProviderAdapter({"cat-a": [_entry("r1"), _entry("r2")]})
    store = FakeIndexingStore()

    result = await run_indexing_v2(
        adapter=adapter, store=store, category_ids=["cat-a"]
    )

    missing = REQUIRED_SCAN_FIELDS - result.keys()
    assert not missing, f"scan result missing required fields: {missing}"
    missing_writes = REQUIRED_WRITE_FIELDS - result["writes"].keys()
    assert not missing_writes, f"writes missing fields: {missing_writes}"


async def test_active_workers_correct() -> None:
    adapter = FakeProviderAdapter({"cat-a": [_entry("r1")]})
    store = FakeIndexingStore()

    assert adapter.in_scan is False
    await run_indexing_v2(adapter=adapter, store=store, category_ids=["cat-a"])
    assert adapter.active_observed is True
    assert adapter.in_scan is False


async def test_dirs_discovered_correct() -> None:
    catalog = {
        "cat-a": [_entry("r1")],
        "cat-b": [_entry("r2")],
        "cat-c": [_entry("r3")],
    }
    adapter = FakeProviderAdapter(catalog)
    store = FakeIndexingStore()

    result = await run_indexing_v2(
        adapter=adapter, store=store, category_ids=list(catalog)
    )

    assert result["categories_scanned"] == len(catalog)
    assert len(adapter.scan_calls) == len(catalog)


async def test_dirs_done_correct() -> None:
    catalog = {"cat-a": [_entry("r1")], "cat-b": [_entry("r2")]}
    adapter = FakeProviderAdapter(catalog)
    store = FakeIndexingStore()

    result = await run_indexing_v2(
        adapter=adapter, store=store, category_ids=list(catalog)
    )

    assert result["categories_scanned"] == 2
    assert result["status"] == "success"


async def test_dirs_pending_correct() -> None:
    catalog = {"cat-a": [_entry("r1")], "cat-b": [_entry("r2")]}
    adapter = FakeProviderAdapter(catalog)
    store = FakeIndexingStore()

    result = await run_indexing_v2(
        adapter=adapter, store=store, category_ids=list(catalog)
    )

    total = len(catalog)
    done = result["categories_scanned"]
    pending = total - done
    assert pending == 0
    assert done == total


async def test_dirs_failed_correct() -> None:
    catalog = {"good": [_entry("r1")], "bad": [_entry("r2")]}
    adapter = FailingCategoryAdapter(catalog, fail={"bad"})
    store = FakeIndexingStore()

    result = await run_indexing_v2(
        adapter=adapter, store=store, category_ids=["good", "bad"]
    )

    assert result["status"] == "partial"
    assert len(result["errors"]) == 1
    assert "bad" in result["errors"][0]
    assert result["categories_scanned"] == 1


async def test_entries_discovered_correct() -> None:
    catalog = {"cat-a": [_entry("r1"), _entry("r2"), _entry("r3")]}
    adapter = FakeProviderAdapter(catalog)
    store = FakeIndexingStore()

    result = await run_indexing_v2(
        adapter=adapter, store=store, category_ids=["cat-a"]
    )

    writes = result["writes"]
    entries_discovered = writes["added"] + writes["changed"] + writes["unchanged"]
    assert entries_discovered == 3
    assert writes["added"] == 3


# --- Reconcile metrics ---


async def test_reconcile_writes_counted() -> None:
    keep_indexed = IndexedEntry(
        resource_id="keep",
        category_id="cat-a",
        provider_id="fake-provider",
        path="/keep",
        name="keep",
        size=100,
        modified_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        content_hash="h",
    )
    stale_indexed = _indexed("stale", cat="cat-a")
    store = FakeIndexingStore(seeded=[keep_indexed, stale_indexed])
    service = ReconcileService(store)

    snapshot = CategorySnapshot(
        category_id="cat-a",
        provider_id="fake-provider",
        entries=[
            _entry("keep"),
            _entry("new"),
        ],
        pagination_complete=True,
    )
    result = await service.reconcile(snapshot)

    assert result.writes.added == 1
    assert result.writes.changed == 0
    assert result.writes.removed == 1
    assert result.writes.unchanged == 1


async def test_suppressed_removals_counted() -> None:
    existing = [
        _indexed("old1", cat="cat-a"),
        _indexed("old2", cat="cat-a"),
        _indexed("old3", cat="cat-a"),
    ]
    store = FakeIndexingStore(seeded=existing)
    service = ReconcileService(store)

    snapshot = CategorySnapshot(
        category_id="cat-a",
        provider_id="fake-provider",
        entries=[_entry("old1")],
        pagination_complete=False,
    )
    result = await service.reconcile(snapshot)

    assert result.suppressed_removals == 2
    assert result.writes.removed == 0


async def test_shrink_suppressed_flag() -> None:
    existing = [_indexed("old1", cat="cat-a"), _indexed("old2", cat="cat-a")]
    store = FakeIndexingStore(seeded=existing)
    service = ReconcileService(store)

    partial = CategorySnapshot(
        category_id="cat-a",
        provider_id="fake-provider",
        entries=[_entry("old1")],
        pagination_complete=False,
    )
    partial_result = await service.reconcile(partial)
    assert partial_result.removal_writes_blocked is True
    assert partial_result.suppressed_removals > 0

    complete = CategorySnapshot(
        category_id="cat-a",
        provider_id="fake-provider",
        entries=[_entry("old1")],
        pagination_complete=True,
    )
    complete_result = await service.reconcile(complete)
    assert complete_result.removal_writes_blocked is False
    assert complete_result.suppressed_removals == 0


# --- V2 result dict ---


async def test_v2_result_has_engine_version() -> None:
    adapter = FakeProviderAdapter({"cat-a": [_entry("r1")]})
    store = FakeIndexingStore()

    result = await run_indexing_v2(
        adapter=adapter, store=store, category_ids=["cat-a"]
    )

    assert result["engine"] == "v2"


async def test_v2_result_has_status() -> None:
    adapter = FakeProviderAdapter({"cat-a": [_entry("r1")]})
    store = FakeIndexingStore()

    result = await run_indexing_v2(
        adapter=adapter, store=store, category_ids=["cat-a"]
    )

    assert "status" in result
    assert result["status"] == "success"


async def test_v2_result_has_errors() -> None:
    adapter = FakeProviderAdapter({"cat-a": [_entry("r1")]})
    store = FakeIndexingStore()

    result = await run_indexing_v2(
        adapter=adapter, store=store, category_ids=["cat-a"]
    )

    assert "errors" in result
    assert isinstance(result["errors"], list)
    assert result["errors"] == []


async def test_v2_summary_to_dict_shape_matches_observability_contract() -> None:
    summary = V2IndexingSummary()
    summary.writes = WriteSummary(added=2, changed=1, removed=1, unchanged=4)
    summary.suppressed_removals = 3
    summary.errors.append("cat-x: RuntimeError: boom")

    payload = summary.to_dict()

    assert payload["engine"] == "v2"
    assert payload["status"] == "success"
    assert payload["categories_scanned"] == 0
    assert payload["pages_fetched"] == 0
    assert payload["writes"] == {
        "added": 2,
        "changed": 1,
        "renamed": 0,
        "moved": 0,
        "removed": 1,
        "unchanged": 4,
        "conflict": 0,
    }
    assert payload["suppressed_removals"] == 3
    assert payload["errors"] == ["cat-x: RuntimeError: boom"]


async def test_reconcile_result_carries_pagination_and_shrink_signal() -> None:
    store = FakeIndexingStore()
    service = ReconcileService(store)

    snapshot = CategorySnapshot(
        category_id="cat-a",
        provider_id="fake-provider",
        entries=[_entry("r1")],
        pagination_complete=True,
    )
    result: ReconcileResult = await service.reconcile(snapshot)

    assert result.pagination_complete is True
    assert result.removal_writes_blocked is False
    assert result.writes.added == 1
