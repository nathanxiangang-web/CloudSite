"""Public admin-status helpers for Indexing."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure.status_store import (
    read_v2_sync_progress as _read_v2_sync_progress,
    v2_sync_due as _v2_sync_due,
    toggle_automatic_sync as _toggle_automatic_sync,
)


async def read_v2_sync_progress(
    state: AsyncSession,
) -> dict[str, object]:
    return await _read_v2_sync_progress(state)


async def v2_sync_due(
    state: AsyncSession,
    interval_minutes: int,
) -> bool:
    return await _v2_sync_due(state, interval_minutes)


async def toggle_automatic_sync(
    state: AsyncSession,
) -> bool:
    return await _toggle_automatic_sync(state)


__all__ = [
    "read_v2_sync_progress",
    "v2_sync_due",
    "toggle_automatic_sync",
]
