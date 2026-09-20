"""Persistence adapter for Indexing v2 runtime status."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _as_utc(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _progress_payload(value: object) -> dict[str, object]:
    if not value:
        return {}
    try:
        payload = json.loads(str(value))
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


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
    return _progress_payload(row[0]) if row is not None else {}


async def v2_sync_due(
    state: AsyncSession,
    interval_minutes: int,
    *,
    now: datetime | None = None,
) -> bool:
    """Return whether another v2 sync is due.

    The existing v2 progress row is the single scheduling clock. Its
    updated_at timestamp is refreshed while a run is active and when it
    reaches a terminal state, so no second scheduling state is required.
    """
    row = (
        await state.execute(
            text(
                "SELECT value, updated_at FROM system_settings "
                "WHERE key = :key LIMIT 1"
            ),
            {"key": "v2_sync_progress"},
        )
    ).first()
    if row is None:
        return True

    progress = _progress_payload(row[0])
    if progress.get("status") == "running":
        return False

    updated_at = _as_utc(row[1])
    if updated_at is None:
        return True

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current - updated_at >= timedelta(
        minutes=max(int(interval_minutes), 1)
    )


async def recover_interrupted_v2_sync(
    state: AsyncSession,
) -> bool:
    """Mark a v2_sync_progress row left "running" by a crashed process as failed.

    A row whose status is "running" at process start can never be completed by
    the dead worker, so every sync path treats the run as forever-active and
    blocks scheduling. This folds such rows to "failed" with an explicit
    error_message and commits the change.

    Returns True when a stale running row was recovered, False otherwise.
    """
    from cloudsite.models import SystemSetting

    row = await state.get(SystemSetting, "v2_sync_progress")
    if row is None:
        return False
    progress = _progress_payload(row.value)
    if progress.get("status") != "running":
        return False
    progress["status"] = "failed"
    progress["error_message"] = "interrupted by process restart"
    row.value = json.dumps(progress)
    await state.commit()
    return True


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
    "recover_interrupted_v2_sync",
    "v2_sync_due",
    "toggle_automatic_sync",
]
