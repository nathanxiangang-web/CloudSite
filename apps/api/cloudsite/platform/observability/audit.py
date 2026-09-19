"""Persistence-neutral operation audit writer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import DateTime, text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class OperationLogView:
    level: str
    message: str
    created_at: datetime


async def recent_operation_logs(
    session: AsyncSession,
    *,
    limit: int = 6,
) -> list[OperationLogView]:
    statement = text(
        "SELECT level, message, created_at "
        "FROM operation_logs "
        "ORDER BY id DESC LIMIT :limit"
    ).columns(created_at=DateTime(timezone=True))
    rows = (
        await session.execute(
            statement,
            {"limit": max(int(limit), 0)},
        )
    ).mappings().all()
    return [
        OperationLogView(
            level=str(row["level"]),
            message=str(row["message"]),
            created_at=row["created_at"],
        )
        for row in rows
    ]


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


__all__ = [
    "OperationLogView",
    "recent_operation_logs",
    "write_operation_log",
]
