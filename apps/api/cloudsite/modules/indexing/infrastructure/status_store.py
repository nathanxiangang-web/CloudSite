"""Read-only persistence adapter for Indexing runtime status."""

from __future__ import annotations

import json

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


__all__ = ["read_v2_sync_progress"]
