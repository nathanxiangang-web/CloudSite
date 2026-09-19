"""Public admin-status helpers for Indexing."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure.indexing_engine import use_indexing_v2
from ..application.admin_sync import validate_manual_sync_paths
from ..infrastructure.status_store import (
    read_sync_circuit_status as _read_sync_circuit_status,
    read_v2_sync_progress as _read_v2_sync_progress,
    toggle_automatic_sync as _toggle_automatic_sync,
)


def indexing_v2_enabled() -> bool:
    return use_indexing_v2()


async def read_v2_sync_progress(
    state: AsyncSession,
) -> dict[str, object]:
    return await _read_v2_sync_progress(state)


async def read_sync_circuit_status(
    state: AsyncSession,
) -> dict[str, object]:
    return await _read_sync_circuit_status(state)


async def toggle_automatic_sync(
    state: AsyncSession,
) -> bool:
    return await _toggle_automatic_sync(state)


__all__ = [
    "indexing_v2_enabled",
    "read_v2_sync_progress",
    "read_sync_circuit_status",
    "toggle_automatic_sync",
    "validate_manual_sync_paths",
]
