"""Provider exception matrix tests (R1 P0 gap #2, V2 doc section 61).

Uses the merged FaultInjector infrastructure to test scan behaviour under
various provider exception states.  Verifies the P0 invariant: existing
indexed entries are never mistakenly deleted when the provider fails or
returns partial data.

Hard errors (401/403/500/502/503) propagate through AListProviderAdapter
and are caught by run_indexing_v2 per-category isolation -> status="partial"
with errors and no reconcile writes.

Soft/transient faults (429/timeout/reset/malformed/null/empty) are handled
by FaultAwareScanAdapter, a test-only ProviderAdapter that catches provider
failures and returns pagination_complete=False so ReconcileService suppresses
removals while still reporting the changes.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import pytest

from cloudsite.modules.indexing.application.reconcile import ReconcileService
from cloudsite.modules.indexing.application.scan_category import ScanCategoryService
from cloudsite.modules.indexing.domain.snapshot import SnapshotEntry
from cloudsite.modules.indexing.infrastructure.alist_adapter import AListProviderAdapter
from cloudsite.modules.indexing.infrastructure.legacy_bridge import run_indexing_v2
from cloudsite.modules.indexing.infrastructure.provider_adapter import (
    ProviderCapabilities,
)
from cloudsite.modules.indexing.infrastructure.repository import IndexedEntry
from cloudsite.modules.providers.contracts.public import ProviderScanRoot
from fault_injection import (
    FaultInjector,
    ProviderDisconnectError,
    ProviderRateLimitError,
)


# ---------------------------------------------------------------------------
# HTTP-style provider exceptions
# ---------------------------------------------------------------------------


class ProviderHttpError(Exception):
    """Base HTTP error from a provider."""

    def __init__(self, status: int, message: str = "") -> None:
        self.status = status
        super().__init__(f"HTTP {status}: {message}")


class UnauthorizedError(ProviderHttpError):
    def __init__(self) -> None:
        super().__init__(401, "unauthorized")


class ForbiddenError(ProviderHttpError):
    def __init__(self) -> None:
        super().__init__(403, "forbidden")


class RateLimitHttpError(ProviderHttpError):
    def __init__(self) -> None:
        super().__init__(429, "rate limited")


class InternalServerError(ProviderHttpError):
    def __init__(self) -> None:
        super().__init__(500, "internal server error")


class BadGatewayError(ProviderHttpError):
    def __init__(self) -> None:
        super().__init__(502, "bad gateway")


class ServiceUnavailableError(ProviderHttpError):
    def __init__(self) -> None:
        super().__init__(503, "service unavailable")


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeAListProvider:
    """Minimal ProviderScanPort returning a small deterministic listing.

    Returns one file and one empty subdirectory for the root path, and an
    empty listing for any subdirectory so the BFS traversal terminates.
    """

    async def list_path(
        self, path: str, refresh: bool = False, strict: bool = False
    ) -> list[dict[str, Any]]:
        if path.rstrip("/").endswith("/subdir"):
            return []
        return [
            {
                "name": "file1.txt",
                "is_dir": False,
                "size": 100,
                "modified": "2026-01-01T00:00:00Z",
            },
            {"name": "subdir", "is_dir": True, "size": 0},
        ]

    async def get_metadata(self, path: str) -> dict[str, Any]:
        return {"name": path.rsplit("/", 1)[-1], "size": 100}


class FakeIndexingStore:
    """In-memory IndexingStore recording remove/upsert calls."""

    def __init__(self, seeded: list[IndexedEntry] | None = None) -> None:
        self._entries: dict[str, IndexedEntry] = {
            e.resource_id: e for e in (seeded or [])
        }
        self.remove_calls: int = 0
        self.upsert_calls: int = 0
        self.removed_ids: list[str] = []

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
        self.removed_ids.extend(resource_ids)
        self.remove_calls += 1
        return removed

    async def touch_unchanged(self, resource_ids: list[str]) -> int:
        return len(resource_ids)

    def has(self, resource_id: str) -> bool:
        return resource_id in self._entries

    def count(self) -> int:
        return len(self._entries)


class FaultAwareScanAdapter:
    """Test-only ProviderAdapter that converts provider faults to partial scans.

    Wraps a FaultInjector-wrapped provider.  When list_path raises or returns
    a non-list / empty value, the adapter returns (entries, None, False) so
    ReconcileService suppresses removals -- the P0 invariant.  Normal listings
    produce pagination_complete=True.
    """

    def __init__(
        self,
        provider: Any,
        roots: list[ProviderScanRoot] | tuple[ProviderScanRoot, ...],
    ) -> None:
        self._provider = provider
        self._roots = {f"root:{r.root_mapping_id}": r for r in roots}

    @property
    def provider_id(self) -> str:
        return "fault-aware-test"

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
        root = self._roots.get(category_id)
        if root is None:
            return [], None, True

        root_path = root.storage_path
        root_entry = SnapshotEntry(
            resource_id=f"folder:{root.root_mapping_id}:{root_path}",
            path=root_path,
            name=root.display_name,
            metadata={
                "is_dir": True,
                "root_mapping_id": root.root_mapping_id,
                "depth": 0,
            },
        )

        try:
            items = await self._provider.list_path(root_path)
        except Exception:
            return [root_entry], None, False

        if not isinstance(items, list) or len(items) == 0:
            return [root_entry], None, False

        entries: list[SnapshotEntry] = [root_entry]
        for item in items:
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            is_dir = bool(item.get("is_dir"))
            item_path = f"{root_path.rstrip('/')}/{name}"
            entries.append(
                SnapshotEntry(
                    resource_id=(
                        f"{'folder' if is_dir else 'resource'}:"
                        f"{root.root_mapping_id}:{item_path}"
                    ),
                    path=item_path,
                    name=name,
                    size=int(item.get("size") or 0) if not is_dir else None,
                    metadata={
                        "is_dir": is_dir,
                        "root_mapping_id": root.root_mapping_id,
                        "depth": 1,
                    },
                )
            )
        return entries, None, True

    async def inspect(self, request: Any) -> Any:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ROOT_A = ProviderScanRoot(
    root_mapping_id=100,
    content_type="software",
    storage_path="/test-a",
    display_name="Test A",
)
ROOT_B = ProviderScanRoot(
    root_mapping_id=200,
    content_type="software",
    storage_path="/test-b",
    display_name="Test B",
)

CAT_A = "root:100"
CAT_B = "root:200"
PROVIDER_ID_ALIST = "generic_alist"
PROVIDER_ID_FAULT_AWARE = "fault-aware-test"


def _injector() -> FaultInjector:
    return FaultInjector(FakeAListProvider())


def _alist_adapter(provider: Any, roots: list[ProviderScanRoot] | None = None) -> AListProviderAdapter:
    return AListProviderAdapter(provider, roots or [ROOT_A])


def _fault_aware_adapter(
    provider: Any, roots: list[ProviderScanRoot] | None = None
) -> FaultAwareScanAdapter:
    return FaultAwareScanAdapter(provider, roots or [ROOT_A])


def _seeded_entry(
    rid: str = "existing-file-1",
    category_id: str = CAT_A,
    provider_id: str = PROVIDER_ID_ALIST,
) -> IndexedEntry:
    return IndexedEntry(
        resource_id=rid,
        category_id=category_id,
        provider_id=provider_id,
        path="/test-a/old_file.txt",
        name="old_file.txt",
        size=50,
    )


async def _run(
    adapter: Any,
    store: FakeIndexingStore,
    categories: list[str] | None = None,
) -> dict[str, Any]:
    return await run_indexing_v2(
        adapter=adapter,
        store=store,
        category_ids=categories or [CAT_A],
    )


# ---------------------------------------------------------------------------
# Hard error tests -- exception propagates, run_indexing_v2 isolates per
# category, reconcile never runs, existing entries preserved.
# ---------------------------------------------------------------------------


async def test_401_unauthorized() -> None:
    provider = _injector().fail_on_path("/test-a", UnauthorizedError())
    adapter = _alist_adapter(provider)
    store = FakeIndexingStore(seeded=[_seeded_entry()])

    result = await _run(adapter, store)

    assert result["status"] == "partial"
    assert len(result["errors"]) == 1
    assert "401" in result["errors"][0]
    assert result["writes"]["removed"] == 0
    assert store.remove_calls == 0
    assert store.has("existing-file-1")


async def test_403_forbidden_other_categories_continue() -> None:
    provider = _injector().fail_on_path("/test-a", ForbiddenError())
    adapter = _alist_adapter(provider, [ROOT_A, ROOT_B])
    store = FakeIndexingStore(seeded=[_seeded_entry()])

    result = await _run(adapter, store, [CAT_A, CAT_B])

    assert result["status"] == "partial"
    assert any("403" in e for e in result["errors"])
    assert result["categories_scanned"] == 1
    assert store.remove_calls == 0
    assert store.has("existing-file-1")


async def test_500_server_error() -> None:
    provider = _injector().fail_on_path("/test-a", InternalServerError())
    adapter = _alist_adapter(provider)
    store = FakeIndexingStore(seeded=[_seeded_entry()])

    result = await _run(adapter, store)

    assert result["status"] == "partial"
    assert any("500" in e for e in result["errors"])
    assert store.remove_calls == 0
    assert store.has("existing-file-1")


async def test_502_bad_gateway() -> None:
    provider = _injector().fail_on_path("/test-a", BadGatewayError())
    adapter = _alist_adapter(provider)
    store = FakeIndexingStore(seeded=[_seeded_entry()])

    result = await _run(adapter, store)

    assert result["status"] == "partial"
    assert any("502" in e for e in result["errors"])
    assert store.remove_calls == 0
    assert store.has("existing-file-1")


async def test_503_service_unavailable() -> None:
    provider = _injector().fail_on_path("/test-a", ServiceUnavailableError())
    adapter = _alist_adapter(provider)
    store = FakeIndexingStore(seeded=[_seeded_entry()])

    result = await _run(adapter, store)

    assert result["status"] == "partial"
    assert any("503" in e for e in result["errors"])
    assert store.remove_calls == 0
    assert store.has("existing-file-1")


# ---------------------------------------------------------------------------
# Soft / transient fault tests -- FaultAwareScanAdapter catches the fault and
# returns pagination_complete=False.  ReconcileService suppresses removals.
# ---------------------------------------------------------------------------


async def test_429_rate_limit() -> None:
    provider = _injector().fail_on_path("/test-a", RateLimitHttpError())
    adapter = _fault_aware_adapter(provider)
    store = FakeIndexingStore(seeded=[_seeded_entry(provider_id=PROVIDER_ID_FAULT_AWARE)])

    result = await _run(adapter, store)

    assert result["status"] == "success"
    assert result["writes"]["removed"] == 0
    assert result["suppressed_removals"] >= 1
    assert store.remove_calls == 0
    assert store.has("existing-file-1")

    scan_service = ScanCategoryService(adapter)
    scan_result = await scan_service.scan(CAT_A)
    assert scan_result.snapshot.pagination_complete is False


async def test_timeout() -> None:
    provider = _injector().fail_on_path("/test-a", asyncio.TimeoutError())
    adapter = _fault_aware_adapter(provider)
    store = FakeIndexingStore(seeded=[_seeded_entry(provider_id=PROVIDER_ID_FAULT_AWARE)])

    result = await _run(adapter, store)

    assert result["status"] == "success"
    assert result["writes"]["removed"] == 0
    assert result["suppressed_removals"] >= 1
    assert store.remove_calls == 0
    assert store.has("existing-file-1")

    scan_service = ScanCategoryService(adapter)
    scan_result = await scan_service.scan(CAT_A)
    assert scan_result.snapshot.pagination_complete is False


async def test_connection_reset() -> None:
    provider = _injector().fail_on_path(
        "/test-a", ConnectionResetError("connection reset")
    )
    adapter = _fault_aware_adapter(provider)
    store = FakeIndexingStore(seeded=[_seeded_entry(provider_id=PROVIDER_ID_FAULT_AWARE)])

    result = await _run(adapter, store)

    assert result["status"] == "success"
    assert result["writes"]["removed"] == 0
    assert result["suppressed_removals"] >= 1
    assert store.remove_calls == 0
    assert store.has("existing-file-1")


async def test_malformed_response() -> None:
    provider = _injector().return_malformed_on_path("/test-a")
    adapter = _fault_aware_adapter(provider)
    store = FakeIndexingStore(seeded=[_seeded_entry(provider_id=PROVIDER_ID_FAULT_AWARE)])

    result = await _run(adapter, store)

    assert result["status"] == "success"
    assert result["writes"]["removed"] == 0
    assert result["suppressed_removals"] >= 1
    assert store.remove_calls == 0
    assert store.has("existing-file-1")

    scan_service = ScanCategoryService(adapter)
    scan_result = await scan_service.scan(CAT_A)
    assert scan_result.snapshot.pagination_complete is False


async def test_null_response() -> None:
    injector = _injector()

    async def null_list(*args: Any, **kwargs: Any) -> Any:
        return None

    injector.list_path = null_list  # type: ignore[method-assign]
    adapter = _fault_aware_adapter(injector)
    store = FakeIndexingStore(seeded=[_seeded_entry(provider_id=PROVIDER_ID_FAULT_AWARE)])

    result = await _run(adapter, store)

    assert result["status"] == "success"
    assert result["writes"]["removed"] == 0
    assert result["suppressed_removals"] >= 1
    assert store.remove_calls == 0
    assert store.has("existing-file-1")


async def test_empty_response() -> None:
    provider = _injector().return_empty_on_path("/test-a")
    adapter = _fault_aware_adapter(provider)
    store = FakeIndexingStore(seeded=[_seeded_entry(provider_id=PROVIDER_ID_FAULT_AWARE)])

    result = await _run(adapter, store)

    assert result["status"] == "success"
    assert result["writes"]["removed"] == 0
    assert result["suppressed_removals"] >= 1
    assert store.remove_calls == 0
    assert store.has("existing-file-1")

    scan_service = ScanCategoryService(adapter)
    scan_result = await scan_service.scan(CAT_A)
    assert scan_result.snapshot.pagination_complete is False


# ---------------------------------------------------------------------------
# Recovery test -- first scan fails, second scan recovers and succeeds.
# ---------------------------------------------------------------------------


async def test_partial_then_recovery() -> None:
    failing_provider = _injector().fail_on_path(
        "/test-a", InternalServerError()
    )
    failing_adapter = _fault_aware_adapter(failing_provider)
    store = FakeIndexingStore(seeded=[_seeded_entry(provider_id=PROVIDER_ID_FAULT_AWARE)])

    first = await _run(failing_adapter, store)

    assert first["status"] == "success"
    assert first["suppressed_removals"] >= 1
    assert store.has("existing-file-1")

    recovered_provider = _injector()
    recovered_adapter = _fault_aware_adapter(recovered_provider)

    second = await _run(recovered_adapter, store)

    assert second["status"] == "success"
    assert second["writes"]["added"] >= 1
    assert second["suppressed_removals"] == 0
