"""Legacy-to-v2 indexing bridge.

When CLOUDSITE_INDEXING_ENGINE=v2, :func:`run_indexing_v2` is called
instead of the legacy rolling window. It wires the new
``ScanCategoryService`` and ``ReconcileService`` to a provider adapter
and indexing store, executes a scan+reconcile pass for each requested
category, and returns a summary dict shaped like
``run_due_rolling_window``'s result so callers can treat both engines
uniformly.

Production wiring (real adapter/store factories) is added in a later
change; until then callers inject fakes or receive a ``skipped`` status.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..application.reconcile import ReconcileResult, ReconcileService, WriteSummary
from ..application.scan_category import ScanCategoryResult, ScanCategoryService
from .provider_adapter import ProviderAdapter
from .repository import IndexingStore


@dataclass(slots=True)
class V2IndexingSummary:
    status: str = "success"
    engine: str = "v2"
    categories_scanned: int = 0
    pages_fetched: int = 0
    writes: WriteSummary = field(default_factory=WriteSummary)
    suppressed_removals: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "engine": self.engine,
            "categories_scanned": self.categories_scanned,
            "pages_fetched": self.pages_fetched,
            "writes": {
                "added": self.writes.added,
                "changed": self.writes.changed,
                "removed": self.writes.removed,
                "unchanged": self.writes.unchanged,
            },
            "suppressed_removals": self.suppressed_removals,
            "errors": list(self.errors),
        }


async def run_indexing_v2(
    *,
    adapter: ProviderAdapter | None = None,
    store: IndexingStore | None = None,
    category_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Run one indexing v2 scan+reconcile pass.

    ``adapter``/``store`` are injected by callers: tests wire fakes,
    production wiring will be added in a later change. When either is
    ``None`` the pass is reported as ``skipped`` so the scheduler can
    fall back safely without raising.
    """
    if adapter is None or store is None:
        return {
            "status": "skipped",
            "engine": "v2",
            "reason": "adapter_or_store_unavailable",
        }

    scan_service = ScanCategoryService(adapter)
    reconcile_service = ReconcileService(store)
    categories = category_ids or []
    summary = V2IndexingSummary()

    for category_id in categories:
        try:
            scan_result: ScanCategoryResult = await scan_service.scan(category_id)
            reconcile_result: ReconcileResult = await reconcile_service.reconcile(
                scan_result.snapshot
            )
            summary.categories_scanned += 1
            summary.pages_fetched += scan_result.pages_fetched
            summary.writes.added += reconcile_result.writes.added
            summary.writes.changed += reconcile_result.writes.changed
            summary.writes.removed += reconcile_result.writes.removed
            summary.writes.unchanged += reconcile_result.writes.unchanged
            summary.suppressed_removals += reconcile_result.suppressed_removals
        except Exception as exc:  # noqa: BLE001 - per-category isolation
            summary.errors.append(f"{category_id}: {type(exc).__name__}: {exc}")

    if summary.errors:
        summary.status = "partial"
    return summary.to_dict()


__all__ = ["V2IndexingSummary", "run_indexing_v2"]