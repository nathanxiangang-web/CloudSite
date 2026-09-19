"""Compatibility helpers still used by the Indexing v2 composition layer.

The legacy full-sync execution engine has been retired. This module remains
temporarily only for three compatibility helpers that are still consumed by
startup/v2 composition and will be moved behind their owning boundaries later.
"""

from datetime import datetime, timezone

from sqlalchemy import select, update

from .alist import AListClient
from .crypto import decrypt_secret
from .database import IndexSession, StateSession
from .models import (
    AListConnection,
    ContentRootMapping,
    OperationLog,
    SyncRun,
)


async def load_all_connections_and_roots() -> list[
    tuple[AListConnection, AListClient, list[ContentRootMapping]]
]:
    """Load every enabled provider connection with its enabled content roots."""
    result: list[
        tuple[AListConnection, AListClient, list[ContentRootMapping]]
    ] = []
    async with StateSession() as session:
        connections = (
            await session.scalars(
                select(AListConnection)
                .where(AListConnection.enabled.is_(True))
                .order_by(AListConnection.id)
            )
        ).all()
        for connection in connections:
            if not connection.password_ciphertext:
                continue
            roots = list(
                (
                    await session.scalars(
                        select(ContentRootMapping)
                        .where(
                            ContentRootMapping.enabled.is_(True),
                            ContentRootMapping.connection_id == connection.id,
                        )
                        .order_by(
                            ContentRootMapping.sort_order,
                            ContentRootMapping.id,
                        )
                    )
                ).all()
            )
            if not roots:
                continue
            client = AListClient(
                connection.base_url,
                connection.username,
                decrypt_secret(connection.password_ciphertext),
            )
            result.append((connection, client, roots))
    if not result:
        raise RuntimeError("没有可用的已启用连接及内容根映射")
    return result


async def recover_interrupted_sync_runs() -> None:
    """Close frozen legacy run rows left running by an older process/version."""
    async with IndexSession() as session:
        await session.execute(
            update(SyncRun)
            .where(SyncRun.status == "running")
            .values(
                status="failed",
                finished_at=datetime.now(timezone.utc),
                error_message="同步任务被服务重启或异常中断",
            )
        )
        await session.commit()


async def log_operation(
    module: str,
    action: str,
    message: str,
    level: str = "INFO",
) -> None:
    """Compatibility audit writer used by scheduler/v2 bridge."""
    async with StateSession() as session:
        session.add(
            OperationLog(
                level=level,
                module=module,
                action=action,
                message=message[:2000],
            )
        )
        await session.commit()


__all__ = [
    "load_all_connections_and_roots",
    "recover_interrupted_sync_runs",
    "log_operation",
]
