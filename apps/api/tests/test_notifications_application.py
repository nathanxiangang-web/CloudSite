"""Notifications application boundary behavior tests."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import models as legacy_models  # noqa: F401 - register StateBase tables
from cloudsite.models import OperationLog
from cloudsite.modules.notifications.application.notification_service import (
    create_admin_notification,
    delete_admin_notification,
    delete_notification_for_user,
    list_admin_notifications,
    list_notifications_for_user,
    update_admin_notification,
)
from cloudsite.modules.notifications.domain.errors import (
    NotificationForbidden,
    NotificationNotFound,
)
from cloudsite.modules.notifications.infrastructure.models import Notification
from cloudsite.platform.db import StateBase


async def _store():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)
    return engine, factory


async def test_user_listing_preserves_visibility_expiry_and_ordering():
    engine, factory = await _store()
    now = datetime(2026, 9, 19, 3, 0, tzinfo=timezone.utc)

    async with factory() as session:
        session.add_all(
            [
                Notification(
                    user_id=None,
                    title="global",
                    enabled=True,
                    pinned=False,
                    published_at=now - timedelta(minutes=2),
                ),
                Notification(
                    user_id=7,
                    title="mine-pinned",
                    enabled=True,
                    pinned=True,
                    published_at=now - timedelta(minutes=10),
                ),
                Notification(
                    user_id=7,
                    title="mine-new",
                    enabled=True,
                    pinned=False,
                    published_at=now - timedelta(minutes=1),
                ),
                Notification(
                    user_id=8,
                    title="other",
                    enabled=True,
                    published_at=now,
                ),
                Notification(
                    user_id=7,
                    title="disabled",
                    enabled=False,
                    published_at=now,
                ),
                Notification(
                    user_id=7,
                    title="expired",
                    enabled=True,
                    expires_at=now - timedelta(seconds=1),
                    published_at=now,
                ),
            ]
        )
        await session.commit()

    async with factory() as session:
        items = await list_notifications_for_user(
            session,
            user_id=7,
            now=now,
            limit=30,
        )

    assert [item["title"] for item in items] == [
        "mine-pinned",
        "mine-new",
        "global",
    ]
    await engine.dispose()


async def test_user_delete_only_allows_own_notification():
    engine, factory = await _store()

    async with factory() as session:
        own = Notification(user_id=7, title="own")
        global_row = Notification(user_id=None, title="global")
        other = Notification(user_id=8, title="other")
        session.add_all([own, global_row, other])
        await session.commit()
        own_id = own.id
        global_id = global_row.id
        other_id = other.id

    async with factory() as session:
        with pytest.raises(NotificationForbidden):
            await delete_notification_for_user(
                session,
                notification_id=global_id,
                user_id=7,
            )

    async with factory() as session:
        with pytest.raises(NotificationForbidden):
            await delete_notification_for_user(
                session,
                notification_id=other_id,
                user_id=7,
            )

    async with factory() as session:
        await delete_notification_for_user(
            session,
            notification_id=own_id,
            user_id=7,
        )
        assert await session.get(Notification, own_id) is None

    async with factory() as session:
        with pytest.raises(NotificationNotFound):
            await delete_notification_for_user(
                session,
                notification_id=999999,
                user_id=7,
            )

    await engine.dispose()


async def test_admin_commands_preserve_payload_and_audit_log():
    engine, factory = await _store()

    async with factory() as session:
        created = await create_admin_notification(
            session,
            title="Maintenance",
            body="Tonight",
            level="warning",
            pinned=True,
            enabled=False,
            expires_at=None,
        )
        notification_id = created["id"]
        assert created["source"] == "manual"
        assert created["enabled"] is False

    async with factory() as session:
        updated = await update_admin_notification(
            session,
            notification_id=notification_id,
            changes={
                "title": "Maintenance updated",
                "enabled": True,
            },
        )
        assert updated["title"] == "Maintenance updated"
        assert updated["enabled"] is True
        assert updated["published_at"] is not None

    async with factory() as session:
        items = await list_admin_notifications(session)
        assert [item["id"] for item in items] == [notification_id]

    async with factory() as session:
        await delete_admin_notification(
            session,
            notification_id=notification_id,
        )

    async with factory() as session:
        assert await session.get(Notification, notification_id) is None
        actions = list(
            (
                await session.scalars(
                    select(OperationLog.action)
                    .where(OperationLog.module == "notification")
                    .order_by(OperationLog.id)
                )
            ).all()
        )
        assert actions == [
            "notification_created",
            "notification_updated",
            "notification_deleted",
        ]

    await engine.dispose()
