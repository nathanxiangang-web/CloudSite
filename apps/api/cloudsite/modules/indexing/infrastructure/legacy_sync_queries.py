"""Read-only query boundary for frozen legacy sync state."""

from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.legacy_sync import (
    LegacySyncChangePage,
    LegacySyncChangeView,
    LegacySyncRunView,
)
from .legacy_models import SyncChange, SyncRun


class LegacySyncQueries:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _run_view(row: SyncRun) -> LegacySyncRunView:
        return LegacySyncRunView(
            id=row.id,
            sync_type=row.sync_type,
            status=row.status,
            folders_scanned=row.folders_scanned,
            resources_scanned=row.resources_scanned,
            added_count=row.added_count,
            updated_count=row.updated_count,
            removed_count=row.removed_count,
            started_at=row.started_at,
            finished_at=row.finished_at,
            duration_ms=row.duration_ms,
            error_message=row.error_message,
            current_path=row.current_path,
            roots_total=row.roots_total,
            roots_completed=row.roots_completed,
            roots_failed=row.roots_failed,
        )

    @staticmethod
    def _change_view(row: SyncChange) -> LegacySyncChangeView:
        return LegacySyncChangeView(
            id=row.id,
            object_type=row.object_type,
            object_id=row.object_id,
            change_type=row.change_type,
            old_path=row.old_path,
            new_path=row.new_path,
            created_at=row.created_at,
        )

    async def get_run(self, sync_run_id: int) -> LegacySyncRunView | None:
        row = await self._session.get(SyncRun, sync_run_id)
        if row is None:
            return None
        return self._run_view(row)

    async def list_runs(self, *, limit: int) -> list[LegacySyncRunView]:
        rows = list(
            (
                await self._session.scalars(
                    select(SyncRun)
                    .order_by(desc(SyncRun.id))
                    .limit(limit)
                )
            ).all()
        )
        return [self._run_view(row) for row in rows]

    async def list_recent_changes(
        self,
        *,
        sync_run_id: int,
        limit: int,
    ) -> list[LegacySyncChangeView]:
        rows = list(
            (
                await self._session.scalars(
                    select(SyncChange)
                    .where(SyncChange.sync_run_id == sync_run_id)
                    .order_by(desc(SyncChange.id))
                    .limit(limit)
                )
            ).all()
        )
        return [self._change_view(row) for row in rows]

    async def list_changes(
        self,
        *,
        sync_run_id: int,
        after_change_id: int,
        limit: int,
    ) -> LegacySyncChangePage:
        rows = list(
            (
                await self._session.scalars(
                    select(SyncChange)
                    .where(
                        SyncChange.sync_run_id == sync_run_id,
                        SyncChange.id > after_change_id,
                    )
                    .order_by(SyncChange.id)
                    .limit(limit + 1)
                )
            ).all()
        )
        has_more = len(rows) > limit
        items = tuple(
            self._change_view(row)
            for row in rows[:limit]
        )
        return LegacySyncChangePage(items=items, has_more=has_more)


__all__ = ["LegacySyncQueries"]
