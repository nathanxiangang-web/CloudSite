"""Public admin-status helpers for Indexing."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure.indexing_engine import use_indexing_v2
from ..infrastructure.status_store import (
    read_v2_sync_progress as _read_v2_sync_progress,
)


def indexing_v2_enabled() -> bool:
    return use_indexing_v2()


async def read_v2_sync_progress(
    state: AsyncSession,
) -> dict[str, object]:
    return await _read_v2_sync_progress(state)


__all__ = [
    "indexing_v2_enabled",
    "read_v2_sync_progress",
]
