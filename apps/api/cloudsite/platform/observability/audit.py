"""Persistence-neutral operation audit writer."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def write_operation_log(
    session: AsyncSession,
    *,
    module: str,
    action: str,
    message: str,
    level: str = "INFO",
    principal: str = "",
    actor_user_id: int | None = None,
) -> None:
    await session.execute(
        text(
            "INSERT INTO operation_logs("
            "level, module, action, message, principal, actor_user_id, created_at"
            ") VALUES ("
            ":level, :module, :action, :message, :principal, :actor_user_id, "
            ":created_at)"
        ),
        {
            "level": level,
            "module": module,
            "action": action,
            "message": message,
            "principal": principal,
            "actor_user_id": actor_user_id,
            "created_at": datetime.now(timezone.utc),
        },
    )


async def count_operation_logs(
    session: AsyncSession,
) -> int:
    row = (
        await session.execute(
            text("SELECT COUNT(*) FROM operation_logs")
        )
    ).first()
    return int(row[0] or 0) if row is not None else 0


async def recent_operation_logs(
    session: AsyncSession,
    *,
    limit: int = 6,
) -> list[dict]:
    rows = (
        await session.execute(
            text(
                "SELECT level, message, created_at "
                "FROM operation_logs "
                "ORDER BY id DESC LIMIT :limit"
            ),
            {"limit": max(int(limit), 0)},
        )
    ).all()
    return [
        {
            "level": str(level),
            "message": str(message),
            "created_at": created_at,
        }
        for level, message, created_at in rows
    ]


__all__ = [
    "write_operation_log",
    "count_operation_logs",
    "recent_operation_logs",
]
