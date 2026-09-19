"""Indexing v2 production bridge.

This module wires the v2 ScanCategoryService and ReconcileService to the
provider adapter and injected indexing store. Indexing v2 is the only
production indexing engine; historical 1.x sync data is read-only compatibility
state and is not an execution fallback.

run_indexing_v2_production owns production scan orchestration while callers
inject the store factory, keeping Folder/Resource persistence outside the
Indexing module boundary.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

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
    on_progress: Any = None,
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
            scan_result: ScanCategoryResult = await scan_service.scan(
                category_id, on_progress=on_progress,
            )
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


async def run_indexing_v2_production(
    *,
    store_factory: Callable[[Any], IndexingStore],
) -> dict[str, Any]:
    """Production entry point for v2 indexing.

    Loads AList connections + content roots, builds the provider adapter, and
    runs scan+reconcile for every enabled content type. The application layer
    injects a store factory so Indexing does not own Folder/Resource ORM access.
    """
    import asyncio
    import time

    from cloudsite.indexer import load_all_connections_and_roots, log_operation
    from cloudsite.platform.db import index_session

    from .alist_adapter import AListProviderAdapter

    t0 = time.time()
    await log_operation("sync", "v2_sync_started", "v2 indexing sync started")
    await _update_v2_sync_status("running", 0, 0, 0, "", 0)

    connections = await load_all_connections_and_roots()
    if not connections:
        await _update_v2_sync_status("skipped", 0, 0, 0, "", 0)
        return {"status": "skipped", "engine": "v2", "reason": "no_connections"}

    all_roots: list = []
    for _conn, _client, roots in connections:
        for root in roots:
            if root not in all_roots:
                all_roots.append(root)

    total_summary = V2IndexingSummary()
    total_categories = len(all_roots)
    categories_done = 0
    entries_scanned = 0

    for _conn, client, roots in connections:
        adapter = AListProviderAdapter(client, roots)
        for root in roots:
            root_label = f"{root.alist_path}({root.content_type})"
            await _update_v2_sync_status(
                "running", categories_done, total_categories,
                int(time.time() - t0), root.alist_path, entries_scanned,
            )
            await log_operation(
                "sync", "v2_category_started",
                f"Scanning: {root_label}",
            )
            try:
                async def _on_progress(path: str, count: int) -> None:
                    await _update_v2_sync_status(
                        "running", categories_done, total_categories,
                        int(time.time() - t0), path, entries_scanned + count,
                    )
                async with index_session() as session:
                    store = store_factory(session)
                    result = await run_indexing_v2(
                        adapter=adapter,
                        store=store,
                        category_ids=[root.content_type],
                        on_progress=_on_progress,
                    )
                    await session.commit()
            except asyncio.CancelledError:
                await _update_v2_sync_status(
                    "cancelled", categories_done, total_categories,
                    int(time.time() - t0), root.alist_path, entries_scanned,
                )
                raise
            categories_done += 1
            writes = result.get("writes", {})
            entries_scanned += writes.get("added", 0) + writes.get("changed", 0) + writes.get("unchanged", 0)
            await _update_v2_sync_status(
                "running", categories_done, total_categories,
                int(time.time() - t0), "", entries_scanned,
            )
            if result.get("status") == "success":
                total_summary.categories_scanned += result.get("categories_scanned", 0)
                total_summary.pages_fetched += result.get("pages_fetched", 0)
                total_summary.writes.added += writes.get("added", 0)
                total_summary.writes.changed += writes.get("changed", 0)
                total_summary.writes.removed += writes.get("removed", 0)
                total_summary.writes.unchanged += writes.get("unchanged", 0)
                await log_operation(
                    "sync", "v2_category_completed",
                    f"Done: {root_label} | "
                    f"added={writes.get('added', 0)} changed={writes.get('changed', 0)} "
                    f"removed={writes.get('removed', 0)} unchanged={writes.get('unchanged', 0)}",
                )
            elif result.get("status") == "partial":
                total_summary.errors.extend(result.get("errors", []))
                await log_operation(
                    "sync", "v2_category_partial",
                    f"Partial: {root_label} | errors: {result.get('errors', [])}",
                    level="WARNING",
                )

    elapsed = int(time.time() - t0)
    if total_summary.errors:
        total_summary.status = "partial"
        await log_operation(
            "sync", "v2_sync_failed",
            f"v2 sync completed with errors in {elapsed}s: {total_summary.errors[:3]}",
            level="ERROR",
        )
        await _update_v2_sync_status(
            "failed", categories_done, total_categories, elapsed, "", entries_scanned,
            total_summary.writes.added,
            total_summary.writes.changed,
            total_summary.writes.removed,
            total_summary.writes.unchanged,
        )
    else:
        await log_operation(
            "sync", "v2_sync_completed",
            f"v2 sync completed in {elapsed}s | "
            f"categories={total_summary.categories_scanned} "
            f"added={total_summary.writes.added} "
            f"changed={total_summary.writes.changed} "
            f"removed={total_summary.writes.removed} "
            f"unchanged={total_summary.writes.unchanged}",
        )
        await _update_v2_sync_status(
            "completed", categories_done, total_categories, elapsed, "", entries_scanned,
            total_summary.writes.added,
            total_summary.writes.changed,
            total_summary.writes.removed,
            total_summary.writes.unchanged,
        )
    return total_summary.to_dict()


async def _update_v2_sync_status(
    status: str,
    categories_done: int,
    categories_total: int,
    elapsed_seconds: int,
    current_path: str = "",
    entries_scanned: int = 0,
) -> None:
    """Persist v2 sync progress to SystemSetting for status endpoint."""
    import json

    from cloudsite.platform.db import state_session
    from sqlalchemy import text

    payload = json.dumps({
        "status": status,
        "categories_done": categories_done,
        "categories_total": categories_total,
        "elapsed_seconds": elapsed_seconds,
        "current_path": current_path,
        "entries_scanned": entries_scanned,
    })
    async with state_session() as session:
        await session.execute(
            text(
                "INSERT INTO system_settings(key, value, value_type, updated_at) "
                "VALUES (:key, :value, 'string', CURRENT_TIMESTAMP) "
                "ON CONFLICT(key) DO UPDATE SET "
                "value = excluded.value, "
                "value_type = excluded.value_type, "
                "updated_at = CURRENT_TIMESTAMP"
            ),
            {"key": "v2_sync_progress", "value": payload},
        )
        await session.commit()


__all__ = ["V2IndexingSummary", "run_indexing_v2", "run_indexing_v2_production"]