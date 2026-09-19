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


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
        return (
            parsed
            if parsed.tzinfo
            else parsed.replace(tzinfo=timezone.utc)
        )
    except (TypeError, ValueError):
        return None


async def read_sync_circuit_status(
    state: AsyncSession,
) -> dict[str, object]:
    rows = (
        await state.execute(
            text(
                "SELECT key, value FROM system_settings "
                "WHERE key IN ("
                "'sync_circuit_until', "
                "'sync_circuit_reason', "
                "'sync_circuit_failures'"
                ")"
            )
        )
    ).all()
    values = {str(key): str(value or "") for key, value in rows}
    until = _parse_time(values.get("sync_circuit_until"))
    now = datetime.now(timezone.utc)
    try:
        failures = int(values.get("sync_circuit_failures", "0") or 0)
    except (TypeError, ValueError):
        failures = 0
    return {
        "open": bool(until and until > now),
        "until": until,
        "reason": values.get("sync_circuit_reason", ""),
        "failures": failures,
    }


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


__all__ = [
    "read_v2_sync_progress",
    "read_sync_circuit_status",
    "toggle_automatic_sync",
]
