"""Indexing v2 scan/reconcile regression tests."""
from __future__ import annotations

from datetime import datetime, timezone


from cloudsite.modules.indexing.domain.inspection import (
    InspectionRequest,
    InspectionResult,
)
from cloudsite.modules.indexing.domain.snapshot import SnapshotEntry
from cloudsite.modules.indexing.infrastructure.legacy_bridge import run_indexing_v2
from cloudsite.modules.indexing.infrastructure.provider_adapter import (
    ProviderAdapter,
    ProviderCapabilities,
)
from cloudsite.modules.indexing.infrastructure.repository import (
    IndexedEntry,
    IndexingStore,
)


class FakeProviderAdapter:
    """最小 ProviderAdapter 实现，按 category 返回预设 entries。"""

    def __init__(self, catalog: dict[str, list[SnapshotEntry]]) -> None:
        self._catalog = catalog
        self.scan_calls: list[tuple[str, str | None, int | None]] = []

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
        self.scan_calls.append((category_id, cursor, limit))
        entries = self._catalog.get(category_id, [])
        return list(entries), None, True

    async def inspect(self, request: InspectionRequest) -> InspectionResult:
        return InspectionResult(
            resource_id=request.resource_id,
            provider_id=request.provider_id,
            path="",
            name="",
        )


class FakeIndexingStore:
    """内存 IndexingStore 实现，记录操作并按 resource_id 索引。"""

    def __init__(self, seeded: list[IndexedEntry] | None = None) -> None:
        self._entries: dict[str, IndexedEntry] = {e.resource_id: e for e in (seeded or [])}
        self.upsert_calls: int = 0
        self.remove_calls: int = 0
        self.touch_calls: int = 0

    async def list_indexed(self, *, category_id: str, provider_id: str) -> list[IndexedEntry]:
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
        self.touch_calls += 1
        return len(resource_ids)


def _entry(rid: str, name: str = "f") -> SnapshotEntry:
    return SnapshotEntry(
        resource_id=rid,
        path=f"/{name}",
        name=name,
        size=100,
        modified_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        content_hash="h",
    )


async def test_run_indexing_v2_skipped_without_adapter_or_store() -> None:
    result = await run_indexing_v2()
    assert result["status"] == "skipped"
    assert result["engine"] == "v2"
    assert result["reason"] == "adapter_or_store_unavailable"


async def test_run_indexing_v2_uses_new_services_for_added_entries() -> None:
    adapter = FakeProviderAdapter({"cat-a": [_entry("r1"), _entry("r2")]})
    store = FakeIndexingStore()

    result = await run_indexing_v2(
        adapter=adapter,
        store=store,
        category_ids=["cat-a"],
    )

    assert result["status"] == "success"
    assert result["engine"] == "v2"
    assert result["categories_scanned"] == 1
    assert result["pages_fetched"] == 1
    assert result["writes"]["added"] == 2
    assert result["writes"]["changed"] == 0
    assert result["writes"]["removed"] == 0
    assert result["suppressed_removals"] == 0
    assert adapter.scan_calls == [("cat-a", None, None)]
    assert store.upsert_calls == 1


async def test_run_indexing_v2_detects_removals_when_pagination_complete() -> None:
    seeded = [
        IndexedEntry(
            resource_id="old",
            category_id="cat-a",
            provider_id="fake-provider",
            path="/old",
            name="old",
            size=1,
        )
    ]
    adapter = FakeProviderAdapter({"cat-a": [_entry("r1")]})
    store = FakeIndexingStore(seeded=seeded)

    result = await run_indexing_v2(
        adapter=adapter,
        store=store,
        category_ids=["cat-a"],
    )

    assert result["status"] == "success"
    assert result["writes"]["added"] == 1
    assert result["writes"]["removed"] == 1
    assert result["suppressed_removals"] == 0
    assert store.remove_calls == 1


async def test_run_indexing_v2_isolates_per_category_errors() -> None:
    class ExplodingAdapter(FakeProviderAdapter):
        async def scan_category(self, category_id, *, cursor=None, limit=None, on_progress=None):
            if category_id == "bad":
                raise RuntimeError("boom")
            return await super().scan_category(category_id, cursor=cursor, limit=limit)

    adapter = ExplodingAdapter({"good": [_entry("r1")]})
    store = FakeIndexingStore()

    result = await run_indexing_v2(
        adapter=adapter,
        store=store,
        category_ids=["bad", "good"],
    )

    assert result["status"] == "partial"
    assert result["categories_scanned"] == 1
    assert len(result["errors"]) == 1
    assert "bad" in result["errors"][0]


async def test_run_indexing_v2_empty_category_list_is_success() -> None:
    adapter = FakeProviderAdapter({})
    store = FakeIndexingStore()

    result = await run_indexing_v2(
        adapter=adapter,
        store=store,
        category_ids=[],
    )

    assert result["status"] == "success"
    assert result["categories_scanned"] == 0