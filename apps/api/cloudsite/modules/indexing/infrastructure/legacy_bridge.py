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

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from ..application.reconcile import ReconcileResult, ReconcileService, WriteSummary
from ..application.scan_category import ScanCategoryResult, ScanCategoryService
from .provider_adapter import ProviderAdapter
from .repository import IndexingStore

logger = logging.getLogger(__name__)

GLOBAL_SCAN_CONCURRENCY = 16  # global scan concurrency
RECONCILE_CONCURRENCY = 1     # production reconcile concurrency


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
                "renamed": self.writes.renamed,
                "moved": self.writes.moved,
                "removed": self.writes.removed,
                "unchanged": self.writes.unchanged,
                "conflict": self.writes.conflict,
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

    if not categories:
        return summary.to_dict()

    scan_semaphore = asyncio.Semaphore(GLOBAL_SCAN_CONCURRENCY)
    scan_results: dict[str, ScanCategoryResult] = {}
    scan_errors: dict[str, Exception] = {}

    async def scan_one(category_id: str) -> None:
        async with scan_semaphore:
            try:
                scan_results[category_id] = await scan_service.scan(
                    category_id, on_progress=on_progress,
                )
            except Exception as exc:  # noqa: BLE001 - per-category isolation
                scan_errors[category_id] = exc

    await asyncio.gather(*(scan_one(cid) for cid in categories))

    # Reconcile phase -- single atomic DB transaction (V2 doc section 20).
    # Any exception rolls back the entire reconcile so production stays in
    # its last consistent state.  Staging (scan snapshots / index_scan_entries)
    # is preserved so the caller can retry reconcile without rescanning.
    try:
        for category_id in sorted(categories):
            if category_id in scan_errors:
                exc = scan_errors[category_id]
                summary.errors.append(
                    f"{category_id}: {type(exc).__name__}: {exc}"
                )
                continue
            scan_result = scan_results[category_id]
            reconcile_result: ReconcileResult = await reconcile_service.reconcile(
                scan_result.snapshot
            )
            summary.categories_scanned += 1
            summary.pages_fetched += scan_result.pages_fetched
            summary.writes.added += reconcile_result.writes.added
            summary.writes.changed += reconcile_result.writes.changed
            summary.writes.renamed += reconcile_result.writes.renamed
            summary.writes.moved += reconcile_result.writes.moved
            summary.writes.removed += reconcile_result.writes.removed
            summary.writes.unchanged += reconcile_result.writes.unchanged
            summary.writes.conflict += reconcile_result.writes.conflict
            summary.suppressed_removals += reconcile_result.suppressed_removals
    except Exception as exc:  # noqa: BLE001 - atomic reconcile boundary
        logger.exception(
            "atomic reconcile failed; rolling back transaction, "
            "staging preserved for retry"
        )
        rollback = getattr(store, "rollback", None)
        if rollback is not None:
            await rollback()
        summary.errors.append(f"reconcile: {type(exc).__name__}: {exc}")
        summary.status = "partial"
        return summary.to_dict()

    if summary.errors:
        summary.status = "partial"
    return summary.to_dict()


async def _log_operation(
    module: str,
    action: str,
    message: str,
    level: str = "INFO",
) -> None:
    """Persist an operation log through the platform observability boundary."""
    from cloudsite.platform.db import state_session
    from cloudsite.platform.observability import write_operation_log

    async with state_session() as session:
        await write_operation_log(
            session,
            module=module,
            action=action,
            message=message[:2000],
            level=level,
        )
        await session.commit()


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

    from cloudsite.modules.providers.contracts.public import (
        enabled_provider_scan_sources,
    )
    from cloudsite.platform.db import index_session, state_session

    from .alist_adapter import AListProviderAdapter

    t0 = time.time()
    await _log_operation("sync", "v2_sync_started", "v2 indexing sync started")
    await _update_v2_sync_status("running", 0, 0, 0, "", 0)

    async with state_session() as state:
        sources = await enabled_provider_scan_sources(state)
    if not sources:
        await _update_v2_sync_status("skipped", 0, 0, 0, "", 0)
        return {"status": "skipped", "engine": "v2", "reason": "no_connections"}

    all_roots = [
        root
        for source in sources
        for root in source.roots
    ]

    total_summary = V2IndexingSummary()
    total_categories = len(all_roots)
    categories_done = 0
    entries_scanned = 0

    for source in sources:
        adapter = AListProviderAdapter(source.provider, source.roots)
        for root in source.roots:
            root_label = f"{root.storage_path}({root.content_type})"
            await _update_v2_sync_status(
                "running", categories_done, total_categories,
                int(time.time() - t0), root.storage_path, entries_scanned,
            )
            await _log_operation(
                "sync", "v2_category_started",
                f"Scanning: {root_label}",
            )
            root_failed = False
            try:
                async def _on_progress(recent_paths: list[str], count: int) -> None:
                    metrics = adapter.last_scan_metrics
                    await _update_v2_sync_status(
                        "running", categories_done, total_categories,
                        int(time.time() - t0), "", entries_scanned + count,
                        active_workers=metrics.get("active_workers", 0),
                        directories_done=metrics.get("dirs_done", 0),
                        known_pending=metrics.get("dirs_pending", 0),
                        entries_discovered=entries_scanned + count,
                        recent_paths=recent_paths,
                    )
                async with index_session() as session:
                    store = store_factory(session)
                    result = await run_indexing_v2(
                        adapter=adapter,
                        store=store,
                        category_ids=[f"root:{root.root_mapping_id}"],
                        on_progress=_on_progress,
                    )
                    if result.get("status") == "partial":
                        root_failed = True
                        total_summary.errors.extend(result.get("errors", []))
                    if not root_failed:
                        await session.commit()
            except asyncio.CancelledError:
                await _update_v2_sync_status(
                    "cancelled", categories_done, total_categories,
                    int(time.time() - t0), root.storage_path, entries_scanned,
                )
                raise
            except Exception as exc:  # noqa: BLE001 - per-root isolation
                root_failed = True
                total_summary.errors.append(
                    f"{root_label}: {type(exc).__name__}: {exc}",
                )
                result = {"status": "partial", "errors": [f"{root_label}: {exc}"], "writes": {}}
            categories_done += 1
            writes = result.get("writes", {})
            entries_scanned += writes.get("added", 0) + writes.get("changed", 0) + writes.get("unchanged", 0)
            await _update_v2_sync_status(
                "running", categories_done, total_categories,
                int(time.time() - t0), "", entries_scanned,
            )
            if root_failed:
                await _log_operation(
                    "sync", "v2_category_partial",
                    f"Partial: {root_label} | errors: {result.get('errors', [])}",
                    level="WARNING",
                )
            elif result.get("status") == "success":
                total_summary.categories_scanned += result.get("categories_scanned", 0)
                total_summary.pages_fetched += result.get("pages_fetched", 0)
                total_summary.writes.added += writes.get("added", 0)
                total_summary.writes.changed += writes.get("changed", 0)
                total_summary.writes.renamed += writes.get("renamed", 0)
                total_summary.writes.moved += writes.get("moved", 0)
                total_summary.writes.removed += writes.get("removed", 0)
                total_summary.writes.unchanged += writes.get("unchanged", 0)
                total_summary.writes.conflict += writes.get("conflict", 0)
                await _log_operation(
                    "sync", "v2_category_completed",
                    f"Done: {root_label} | "
                    f"added={writes.get('added', 0)} changed={writes.get('changed', 0)} "
                    f"renamed={writes.get('renamed', 0)} moved={writes.get('moved', 0)} "
                    f"removed={writes.get('removed', 0)} unchanged={writes.get('unchanged', 0)} "
                    f"conflict={writes.get('conflict', 0)}",
                )

    elapsed = int(time.time() - t0)
    if total_summary.errors:
        total_summary.status = "partial"
        await _log_operation(
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
        await _log_operation(
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
    added: int = 0,
    changed: int = 0,
    removed: int = 0,
    unchanged: int = 0,
    *,
    active_workers: int | None = None,
    directories_done: int | None = None,
    known_pending: int | None = None,
    entries_discovered: int | None = None,
    recent_paths: list[str] | None = None,
) -> None:
    """Persist V2 progress while preserving the historical storage contract.

    Legacy-only calls keep the exact historical payload for compatibility.
    Concurrent scanner calls opt into the V2 runtime fields explicitly; the
    Admin API normalizes both shapes to the new truthful status contract.
    """
    import json

    from cloudsite.platform.db import state_session
    from sqlalchemy import text

    has_concurrent_metrics = any(
        value is not None
        for value in (
            active_workers,
            directories_done,
            known_pending,
            entries_discovered,
            recent_paths,
        )
    )

    if not has_concurrent_metrics:
        payload = json.dumps({
            "status": status,
            "categories_done": categories_done,
            "categories_total": categories_total,
            "elapsed_seconds": elapsed_seconds,
            "current_path": current_path,
            "entries_scanned": entries_scanned,
            "added": added,
            "changed": changed,
            "removed": removed,
            "unchanged": unchanged,
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
        return

    from .status_store import write_v2_sync_progress

    if entries_discovered is None:
        entries_discovered = entries_scanned
    if recent_paths is None:
        recent_paths = [current_path] if current_path else []

    async with state_session() as session:
        await write_v2_sync_progress(
            session,
            status=status,
            categories_done=categories_done,
            categories_total=categories_total,
            elapsed_seconds=elapsed_seconds,
            active_workers=active_workers or 0,
            directories_done=directories_done or 0,
            known_pending=known_pending or 0,
            entries_discovered=entries_discovered,
            recent_paths=recent_paths,
            added=added,
            changed=changed,
            removed=removed,
            unchanged=unchanged,
            current_path=current_path,
            entries_scanned=entries_scanned,
        )
        await session.commit()


__all__ = ["V2IndexingSummary", "run_indexing_v2", "run_indexing_v2_production"]