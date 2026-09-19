"""Persistence-neutral system settings helpers."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


SYNC_INTERVAL_OPTIONS = {180, 360, 720, 1440}


async def read_admin_system_settings(
    state: AsyncSession,
) -> dict:
    rows = (
        await state.execute(
            text(
                "SELECT key, value FROM system_settings "
                "WHERE key IN ("
                "'automatic_sync', "
                "'sync_interval_minutes', "
                "'sync_on_startup', "
                "'sync_engine_version', "
                "'initial_index_completed_at'"
                ")"
            )
        )
    ).all()
    values = {str(key): str(value or "") for key, value in rows}
    try:
        interval = int(values.get("sync_interval_minutes", "360"))
    except (TypeError, ValueError):
        interval = 360
    if interval not in SYNC_INTERVAL_OPTIONS:
        interval = 360
    return {
        "automatic_sync": values.get("automatic_sync", "false") == "true",
        "sync_interval_minutes": interval,
        "sync_on_startup": values.get("sync_on_startup", "false") == "true",
        "sync_engine_version": values.get("sync_engine_version") or "1.0",
        "initial_index_completed_at": (
            values.get("initial_index_completed_at") or None
        ),
    }


async def read_setup_completed(
    state: AsyncSession,
) -> bool:
    row = (
        await state.execute(
            text(
                "SELECT value FROM system_settings "
                "WHERE key = 'setup_completed' LIMIT 1"
            )
        )
    ).first()
    if row is None:
        return False
    return str(row[0] or "").lower() in {
        "true",
        "1",
        "yes",
        "on",
    }


async def save_admin_system_settings(
    state: AsyncSession,
    *,
    values: dict,
) -> None:
    now = datetime.now(timezone.utc)
    for key, value in values.items():
        serialized = (
            str(value).lower()
            if isinstance(value, bool)
            else str(value)
        )
        existing = (
            await state.execute(
                text(
                    "SELECT key FROM system_settings "
                    "WHERE key = :key LIMIT 1"
                ),
                {"key": key},
            )
        ).first()
        if existing is None:
            await state.execute(
                text(
                    "INSERT INTO system_settings("
                    "key, value, value_type, updated_at"
                    ") VALUES ("
                    ":key, :value, 'string', :updated_at"
                    ")"
                ),
                {
                    "key": key,
                    "value": serialized,
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
                    "key": key,
                    "value": serialized,
                    "updated_at": now,
                },
            )
    await state.commit()


__all__ = [
    "SYNC_INTERVAL_OPTIONS",
    "read_admin_system_settings",
    "read_setup_completed",
    "save_admin_system_settings",
]
