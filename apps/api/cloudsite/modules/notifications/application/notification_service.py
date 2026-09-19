"""Notifications application services."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....platform.observability.audit import write_operation_log
from ..domain.errors import NotificationForbidden, NotificationNotFound
from ..infrastructure.models import Notification, utcnow


def notification_dict(row: Notification) -> dict:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "title": row.title,
        "body": row.body,
        "level": row.level,
        "pinned": row.pinned,
        "enabled": row.enabled,
        "source": row.source,
        "published_at": row.published_at,
        "expires_at": row.expires_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


async def create_user_notification(
    session: AsyncSession,
    *,
    user_id: int,
    title: str,
    body: str = "",
    level: str = "info",
    source: str,
    enabled: bool = True,
    published_at: datetime | None = None,
) -> int:
    """Create one user notification inside the caller-owned transaction."""
    values = {
        "user_id": user_id,
        "title": title,
        "body": body,
        "level": level,
        "source": source,
        "enabled": enabled,
    }
    if published_at is not None:
        values["published_at"] = published_at
    row = Notification(**values)
    session.add(row)
    await session.flush()
    return int(row.id)


async def list_notifications_for_user(
    session: AsyncSession,
    *,
    user_id: int,
    now: datetime | None = None,
    limit: int = 30,
) -> list[dict]:
    current = now or utcnow()
    rows = list(
        (
            await session.scalars(
                select(Notification)
                .where(
                    Notification.enabled.is_(True),
                    or_(
                        Notification.user_id.is_(None),
                        Notification.user_id == user_id,
                    ),
                    or_(
                        Notification.expires_at.is_(None),
                        Notification.expires_at > current,
                    ),
                )
                .order_by(
                    desc(Notification.pinned),
                    desc(Notification.published_at),
                )
                .limit(limit)
            )
        ).all()
    )
    await session.commit()
    return [notification_dict(row) for row in rows]


async def delete_notification_for_user(
    session: AsyncSession,
    *,
    notification_id: int,
    user_id: int,
) -> None:
    row = await session.get(Notification, notification_id)
    if row is None:
        raise NotificationNotFound
    if row.user_id != user_id:
        raise NotificationForbidden
    await session.delete(row)
    await session.commit()


async def list_admin_notifications(session: AsyncSession) -> list[dict]:
    rows = list(
        (
            await session.scalars(
                select(Notification).order_by(desc(Notification.created_at))
            )
        ).all()
    )
    await session.commit()
    return [notification_dict(row) for row in rows]


async def create_admin_notification(
    session: AsyncSession,
    *,
    title: str,
    body: str,
    level: str,
    pinned: bool,
    enabled: bool,
    expires_at: datetime | None,
) -> dict:
    row = Notification(
        title=title,
        body=body,
        level=level,
        pinned=pinned,
        enabled=enabled,
        source="manual",
        expires_at=expires_at,
    )
    session.add(row)
    await write_operation_log(
        session,
        module="notification",
        action="notification_created",
        message=f"新建通知 {title}",
    )
    await session.commit()
    await session.refresh(row)
    return notification_dict(row)


async def update_admin_notification(
    session: AsyncSession,
    *,
    notification_id: int,
    changes: dict[str, Any],
) -> dict:
    row = await session.get(Notification, notification_id)
    if row is None:
        raise NotificationNotFound

    for field in ("title", "body", "level", "pinned", "expires_at"):
        if field in changes:
            setattr(row, field, changes[field])

    if "enabled" in changes:
        was_enabled = row.enabled
        row.enabled = changes["enabled"]
        if not was_enabled and row.enabled:
            row.published_at = utcnow()

    await write_operation_log(
        session,
        module="notification",
        action="notification_updated",
        message=f"更新通知 #{row.id} {row.title}",
    )
    await session.commit()
    await session.refresh(row)
    return notification_dict(row)


async def delete_admin_notification(
    session: AsyncSession,
    *,
    notification_id: int,
) -> None:
    row = await session.get(Notification, notification_id)
    if row is None:
        raise NotificationNotFound

    await write_operation_log(
        session,
        module="notification",
        action="notification_deleted",
        message=f"删除通知 #{row.id} {row.title}",
    )
    await session.delete(row)
    await session.commit()


__all__ = [
    "notification_dict",
    "create_user_notification",
    "list_notifications_for_user",
    "delete_notification_for_user",
    "list_admin_notifications",
    "create_admin_notification",
    "update_admin_notification",
    "delete_admin_notification",
]
