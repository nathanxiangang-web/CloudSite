"""Read-only query boundary for frozen legacy sync state."""

from __future__ import annotations

from sqlalchemy import select
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

    async def get_run(self, sync_run_id: int) -> LegacySyncRunView | None:
        row = await self._session.get(SyncRun, sync_run_id)
        if row is None:
            return None
        return LegacySyncRunView(id=row.id, status=row.status)

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
            LegacySyncChangeView(
                id=row.id,
                object_type=row.object_type,
                object_id=row.object_id,
                change_type=row.change_type,
            )
            for row in rows[:limit]
        )
        return LegacySyncChangePage(items=items, has_more=has_more)


__all__ = ["LegacySyncQueries"]
