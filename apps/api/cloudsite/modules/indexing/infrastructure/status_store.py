"""Persistence adapter for Indexing v2 runtime status."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

RECENT_PATHS_MAX = 64


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


def _bounded_recent_paths(value: object) -> list[str]:
    if isinstance(value, str):
        paths = [value] if value else []
    elif isinstance(value, (list, tuple)):
        paths = [str(item) for item in value if str(item)]
    else:
        paths = []
    return paths[-RECENT_PATHS_MAX:]


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
    """Mark a v2_sync_progress row left "running" by a crashed process as failed."""
    row = (
        await state.execute(
            text(
                "SELECT value FROM system_settings "
                "WHERE key = :key LIMIT 1"
            ),
            {"key": "v2_sync_progress"},
        )
    ).first()
    if row is None:
        return False
    progress = _progress_payload(row[0])
    if progress.get("status") != "running":
        return False
    progress["status"] = "failed"
    progress["error_message"] = "interrupted by process restart"
    progress["active_workers"] = 0
    progress["known_pending"] = 0
    await state.execute(
        text(
            "UPDATE system_settings SET value = :value, updated_at = :now "
            "WHERE key = :key"
        ),
        {
            "value": json.dumps(progress),
            "now": datetime.now(timezone.utc),
            "key": "v2_sync_progress",
        },
    )
    await state.commit()
    return True


async def write_v2_sync_progress(
    state: AsyncSession,
    *,
    status: str,
    categories_done: int = 0,
    elapsed_seconds: int = 0,
    active_workers: int = 0,
    directories_done: int = 0,
    known_pending: int = 0,
    entries_discovered: int = 0,
    recent_paths: list[str] | tuple[str, ...] | None = None,
    added: int = 0,
    changed: int = 0,
    removed: int = 0,
    unchanged: int = 0,
    # Root totals are known before the scan starts and are truthful. Directory
    # totals are intentionally not persisted because BFS discovers them lazily.
    categories_total: int | None = None,
    current_path: str | list[str] | None = None,
    entries_scanned: int | None = None,
) -> None:
    """Persist truthful V2 concurrent-scan progress.

    Root totals are known up front, while the future directory total is not.
    Persist the root total and expose recent paths plus live queue/worker
    metrics instead of manufacturing a directory percentage.
    """

    if recent_paths is None:
        recent_paths = _bounded_recent_paths(current_path)
    else:
        recent_paths = _bounded_recent_paths(recent_paths)

    roots_total = max(int(categories_total or 0), 0)
    latest_path = recent_paths[-1] if recent_paths else ""

    if entries_scanned is not None and entries_discovered == 0:
        entries_discovered = max(int(entries_scanned), 0)

    payload = json.dumps(
        {
            "status": status,
            "categories_done": max(int(categories_done), 0),
            "categories_total": roots_total,
            "elapsed_seconds": max(int(elapsed_seconds), 0),
            "active_workers": max(int(active_workers), 0),
            "directories_done": max(int(directories_done), 0),
            "known_pending": max(int(known_pending), 0),
            "entries_discovered": max(int(entries_discovered), 0),
            "recent_paths": recent_paths,
            # Compatibility field for old admin clients. Under concurrent
            # scanning this means "most recently observed path", not a single
            # authoritative worker position.
            "current_path": latest_path,
            "added": max(int(added), 0),
            "changed": max(int(changed), 0),
            "removed": max(int(removed), 0),
            "unchanged": max(int(unchanged), 0),
        }
    )
    await state.execute(
        text(
            "INSERT INTO system_settings(key, value, value_type, updated_at) "
            "VALUES (:key, :value, 'string', CURRENT_TIMESTAMP) "
            "ON CONFLICT(key) DO UPDATE SET "
            "value = excluded.value, "
            "value_type = excluded.value_type, "
            "updated_at = CURRENT_TIMESTAMP"
        ),
        {"key": "v2_sync_progress", "value": payload},
    )


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
    "RECENT_PATHS_MAX",
    "read_v2_sync_progress",
    "recover_interrupted_v2_sync",
    "write_v2_sync_progress",
    "v2_sync_due",
    "toggle_automatic_sync",
]
