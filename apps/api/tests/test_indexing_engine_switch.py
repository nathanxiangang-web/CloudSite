"""Indexing v2 scan/reconcile regression tests."""
from __future__ import annotations

from datetime import datetime, timezone


from cloudsite.modules.indexing.domain.inspection import (
    InspectionRequest,
    InspectionResult,
)
from cloudsite.modules.indexing.domain.snapshot import SnapshotEntry
from cloudsite.modules.indexing.infrastructure.alist_adapter import AListProviderAdapter
from cloudsite.modules.indexing.infrastructure.legacy_bridge import run_indexing_v2
from cloudsite.modules.indexing.infrastructure.provider_adapter import (
    ProviderAdapter,
    ProviderCapabilities,
)
from cloudsite.modules.providers.contracts.public import ProviderScanRoot
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
    adapter = FakeProviderAdapter({"cat-a": [_entry("r1", "f1"), _entry("r2", "f2")]})
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


async def test_run_indexing_v2_reports_incomplete_scan_as_partial() -> None:
    class IncompleteAdapter(FakeProviderAdapter):
        async def scan_category(
            self,
            category_id,
            *,
            cursor=None,
            limit=None,
            on_progress=None,
        ):
            entries, next_cursor, _ = await super().scan_category(
                category_id,
                cursor=cursor,
                limit=limit,
            )
            return entries, next_cursor, False

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
    adapter = IncompleteAdapter({"cat-a": [_entry("r1")]})
    store = FakeIndexingStore(seeded=seeded)

    result = await run_indexing_v2(
        adapter=adapter,
        store=store,
        category_ids=["cat-a"],
    )

    assert result["status"] == "partial"
    assert result["writes"]["added"] == 1
    assert result["writes"]["removed"] == 0
    assert result["suppressed_removals"] == 1
    assert store.remove_calls == 0
    assert any("scan incomplete" in error for error in result["errors"])


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

async def test_alist_adapter_keeps_same_type_roots_distinct() -> None:
    class FakeAListClient:
        def __init__(self) -> None:
            self.paths: list[str] = []

        async def list_path(self, path: str):
            self.paths.append(path)
            return [
                {
                    "name": "package.zip",
                    "is_dir": False,
                    "size": 42,
                    "modified": "2026-09-19T00:00:00Z",
                }
            ]

        async def get_metadata(self, path: str):
            return {"name": path.rsplit("/", 1)[-1], "size": 42}

    client = FakeAListClient()
    roots = [
        ProviderScanRoot(
            root_mapping_id=11,
            content_type="software",
            storage_path="/apps-a",
            display_name="Apps A",
        ),
        ProviderScanRoot(
            root_mapping_id=12,
            content_type="software",
            storage_path="/apps-b",
            display_name="Apps B",
        ),
    ]
    adapter = AListProviderAdapter(client, roots)

    first, _, _ = await adapter.scan_category("root:11")
    second, _, _ = await adapter.scan_category("root:12")

    assert client.paths == ["/apps-a", "/apps-b"]
    assert first[0].path == "/apps-a"
    assert first[0].metadata["root_mapping_id"] == 11
    assert first[1].path == "/apps-a/package.zip"
    assert second[0].path == "/apps-b"
    assert second[0].metadata["root_mapping_id"] == 12
    assert second[1].path == "/apps-b/package.zip"


async def test_alist_adapter_calculates_folder_depth_and_direct_counts() -> None:
    class HierarchyAListClient:
        async def list_path(self, path: str):
            if path == "/library":
                return [
                    {"name": "nested", "is_dir": True},
                    {"name": "root.zip", "is_dir": False, "size": 10},
                ]
            if path == "/library/nested":
                return [
                    {"name": "child.zip", "is_dir": False, "size": 20},
                ]
            return []

        async def get_metadata(self, path: str):
            return {"name": path.rsplit("/", 1)[-1]}

    root = ProviderScanRoot(
        root_mapping_id=21,
        content_type="software",
        storage_path="/library",
        display_name="Library",
    )
    adapter = AListProviderAdapter(HierarchyAListClient(), [root])

    entries, _, complete = await adapter.scan_category("root:21")
    by_path = {entry.path: entry for entry in entries}

    assert complete is True
    assert by_path["/library"].metadata["depth"] == 0
    assert by_path["/library"].metadata["child_folder_count"] == 1
    assert by_path["/library"].metadata["resource_count"] == 1
    assert by_path["/library/nested"].metadata["depth"] == 1
    assert by_path["/library/nested"].metadata["child_folder_count"] == 0
    assert by_path["/library/nested"].metadata["resource_count"] == 1
    assert by_path["/library/nested/child.zip"].metadata["depth"] == 2


async def test_alist_adapter_namespaces_same_path_ids_by_root_mapping() -> None:
    class SamePathAListClient:
        async def list_path(self, path: str):
            return [
                {
                    "name": "package.zip",
                    "is_dir": False,
                    "size": 42,
                }
            ]

        async def get_metadata(self, path: str):
            return {"name": path.rsplit("/", 1)[-1]}

    roots = [
        ProviderScanRoot(
            root_mapping_id=31,
            content_type="software",
            storage_path="/shared",
            display_name="Shared A",
        ),
        ProviderScanRoot(
            root_mapping_id=32,
            content_type="software",
            storage_path="/shared",
            display_name="Shared B",
        ),
    ]
    adapter = AListProviderAdapter(SamePathAListClient(), roots)

    first, _, _ = await adapter.scan_category("root:31")
    second, _, _ = await adapter.scan_category("root:32")

    assert first[0].path == second[0].path == "/shared"
    assert first[0].resource_id != second[0].resource_id
    assert first[1].path == second[1].path == "/shared/package.zip"
    assert first[1].resource_id != second[1].resource_id
    assert first[1].metadata["parent_id"] == first[0].resource_id
    assert second[1].metadata["parent_id"] == second[0].resource_id
