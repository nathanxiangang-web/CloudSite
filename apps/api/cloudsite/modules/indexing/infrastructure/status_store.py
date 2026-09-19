"""Read-only persistence adapter for Indexing runtime status."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def read_v2_sync_progress(
    state: AsyncSession,
) -> dict[str, object]:
    row = (
        await state.execute(
            text(
                "SELECT value FROM system_settings "
                "WHERE key = :key LIMIT 1"
            ),
            {"key": "v2_sync_progress"},
        )
    ).first()
    if row is None or not row[0]:
        return {}
    try:
        payload = json.loads(str(row[0]))
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


async def toggle_automatic_sync(
    state: AsyncSession,
) -> bool:
    row = (
        await state.execute(
            text(
                "SELECT value FROM system_settings "
                "WHERE key = :key LIMIT 1"
            ),
            {"key": "automatic_sync"},
        )
    ).first()
    current = bool(
        row is not None
        and str(row[0] or "").strip().lower() == "true"
    )
    enabled = not current
    now = datetime.now(timezone.utc)
    if row is None:
        await state.execute(
            text(
                "INSERT INTO system_settings("
                "key, value, value_type, updated_at"
                ") VALUES (:key, :value, :value_type, :updated_at)"
            ),
            {
                "key": "automatic_sync",
                "value": "true" if enabled else "false",
                "value_type": "string",
                "updated_at": now,
            },
        )
    else:
        await state.execute(
            text(
                "UPDATE system_settings "
                "SET value = :value, updated_at = :updated_at "
                "WHERE key = :key"
            ),
            {
                "key": "automatic_sync",
                "value": "true" if enabled else "false",
                "updated_at": now,
            },
        )
    await state.commit()
    return enabled


__all__ = ["read_v2_sync_progress", "toggle_automatic_sync"]
