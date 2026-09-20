"""Catalog release notification contract tests."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import models as legacy_models  # noqa: F401 - register metadata
from cloudsite.models import Notification, User
from cloudsite.modules.catalog.application.release_notifications import (
    notify_release_subscribers,
)
from cloudsite.modules.catalog.infrastructure.models import (
    CatalogEntry,
    CatalogRelease,
    CatalogReleaseNotification,
    CatalogSubscription,
)
from cloudsite.platform.db import StateBase


async def test_release_notification_uses_notifications_contract_and_remains_deduplicated():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)

    async with factory() as session:
        user = User(
            username="catalog-user",
            username_normalized="catalog-user",
            password_hash="x",
            status="active",
        )
        entry = CatalogEntry(
            entry_id="ce_" + "1" * 32,
            content_type="software",
            slug="catalog-app",
            title="Catalog App",
            status="published",
        )
        release = CatalogRelease(
            release_id="cr_" + "2" * 32,
            entry_id=entry.entry_id,
            slug="v2",
            title="v2",
            release_notes="new bits",
            status="published",
        )
        session.add_all([user, entry, release])
        await session.flush()
        session.add(
            CatalogSubscription(
                user_id=user.id,
                entry_id=entry.entry_id,
                notify_enabled=True,
            )
        )
        await session.commit()
        user_id = user.id
        release_id = release.release_id
        entry_id = entry.entry_id

    async with factory() as session:
        release = await session.get(CatalogRelease, release_id)
        entry = await session.get(CatalogEntry, entry_id)
        assert release is not None
        assert entry is not None

        first = await notify_release_subscribers(
            session,
            release=release,
            entry=entry,
        )
        second = await notify_release_subscribers(
            session,
            release=release,
            entry=entry,
        )
        assert first == 1
        assert second == 0
        await session.commit()

    async with factory() as session:
        notifications = list(
            (
                await session.scalars(
                    select(Notification).where(Notification.user_id == user_id)
                )
            ).all()
        )
        dedup = list(
            (
                await session.scalars(
                    select(CatalogReleaseNotification).where(
                        CatalogReleaseNotification.user_id == user_id
                    )
                )
            ).all()
        )
        assert len(notifications) == 1
        assert notifications[0].source == "catalog_release"
        assert "v2" in notifications[0].title
        assert len(dedup) == 1
        assert dedup[0].notification_id == notifications[0].id

    await engine.dispose()
