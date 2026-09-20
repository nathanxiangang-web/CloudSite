from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..domain.snapshot import CategorySnapshot, SnapshotEntry
from ..infrastructure.provider_adapter import ProviderAdapter


@dataclass(slots=True)
class ScanCategoryResult:
    snapshot: CategorySnapshot
    pages_fetched: int
    cursor_exhausted: bool
    active_workers: int = 0
    dirs_done: int = 0
    dirs_pending: int = 0
    entries_discovered: int = 0


class ScanCategoryService:
    """Scan a provider category into a CategorySnapshot.

    Iterates provider pages until the cursor is exhausted or the provider
    signals pagination_complete=False (partial page). The resulting
    snapshot.pagination_complete is True only when every fetched page was
    fully enumerated; a single incomplete page marks the whole snapshot as
    partial so downstream reconciliation can suppress removals.
    """

    def __init__(self, adapter: ProviderAdapter) -> None:
        self._adapter = adapter

    async def scan(
        self,
        category_id: str,
        *,
        max_pages: int = 100,
        page_size: int | None = None,
        on_progress: Any = None,
    ) -> ScanCategoryResult:
        caps = self._adapter.capabilities
        if not caps.supports_scan:
            raise NotImplementedError(
                f'Provider {self._adapter.provider_id} does not support scan'
            )

        all_entries: list[SnapshotEntry] = []
        cursor: str | None = None
        pages = 0
        fully_complete = True
        last_cursor: str | None = None
        metrics: dict[str, int] = {
            "active_workers": 0,
            "dirs_done": 0,
            "dirs_pending": 0,
            "entries_discovered": 0,
        }

        while pages < max_pages:
            limit = page_size or caps.max_page_size
            entries, next_cursor, page_complete = await self._adapter.scan_category(
                category_id, cursor=cursor, limit=limit, on_progress=on_progress,
            )
            all_entries.extend(entries)
            pages += 1
            last_cursor = next_cursor

            if not page_complete:
                fully_complete = False

            page_metrics = getattr(self._adapter, "last_scan_metrics", {})
            if page_metrics:
                metrics["active_workers"] = page_metrics.get("active_workers", 0)
                metrics["dirs_pending"] = page_metrics.get("dirs_pending", 0)
                metrics["dirs_done"] += page_metrics.get("dirs_done", 0)
                metrics["entries_discovered"] += page_metrics.get(
                    "entries_discovered", 0
                )

            if next_cursor is None:
                break
            cursor = next_cursor

        snapshot = CategorySnapshot(
            category_id=category_id,
            provider_id=self._adapter.provider_id,
            entries=all_entries,
            pagination_complete=fully_complete,
        )
        return ScanCategoryResult(
            snapshot=snapshot,
            pages_fetched=pages,
            cursor_exhausted=last_cursor is None,
            active_workers=metrics["active_workers"],
            dirs_done=metrics["dirs_done"],
            dirs_pending=metrics["dirs_pending"],
            entries_discovered=metrics["entries_discovered"],
        )


__all__ = ['ScanCategoryResult', 'ScanCategoryService']