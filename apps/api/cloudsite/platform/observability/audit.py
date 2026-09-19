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


__all__ = ["write_operation_log"]
