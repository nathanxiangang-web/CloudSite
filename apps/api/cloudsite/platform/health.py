"""Persistence-neutral health probe helpers."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def check_database_health(
    state: AsyncSession,
) -> tuple[str, str | None]:
    try:
        await state.execute(
            text("SELECT key FROM system_settings LIMIT 1")
        )
        return "healthy", None
    except Exception as exc:
        return "unhealthy", str(exc)


async def health_checks_enabled(
    state: AsyncSession,
) -> bool:
    try:
        row = (
            await state.execute(
                text(
                    "SELECT value FROM system_settings "
                    "WHERE key = :key LIMIT 1"
                ),
                {"key": "health_check_enabled"},
            )
        ).first()
    except Exception:
        return True
    if row is None:
        return True
    return str(row[0] or "").lower() not in {
        "false",
        "0",
        "no",
        "off",
    }


async def persist_health_component(
    state: AsyncSession,
    *,
    component: str,
    status: str,
    error: str | None,
) -> None:
    try:
        row = (
            await state.execute(
                text(
                    "SELECT id FROM health_check_state "
                    "WHERE component = :component LIMIT 1"
                ),
                {"component": component},
            )
        ).first()
        payload = {
            "component": component,
            "status": status,
            "last_check_at": utcnow_iso(),
            "last_error": error,
        }
        if row is None:
            await state.execute(
                text(
                    "INSERT INTO health_check_state("
                    "component, status, last_check_at, last_error"
                    ") VALUES ("
                    ":component, :status, :last_check_at, :last_error"
                    ")"
                ),
                payload,
            )
        else:
            await state.execute(
                text(
                    "UPDATE health_check_state "
                    "SET status = :status, "
                    "last_check_at = :last_check_at, "
                    "last_error = :last_error "
                    "WHERE component = :component"
                ),
                payload,
            )
        await state.commit()
    except Exception:
        await state.rollback()


__all__ = [
    "check_database_health",
    "health_checks_enabled",
    "persist_health_component",
    "utcnow_iso",
]
