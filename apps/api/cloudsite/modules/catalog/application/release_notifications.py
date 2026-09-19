"""Catalog release subscriber notification write side."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...notifications.contracts.public import create_user_notification
from ..infrastructure.models import (
    CatalogEntry,
    CatalogRelease,
    CatalogReleaseNotification,
    CatalogSubscription,
    utcnow,
)


async def notify_release_subscribers(
    state: AsyncSession,
    *,
    release: CatalogRelease,
    entry: CatalogEntry,
) -> int:
    if release.status != "published" or entry.status != "published":
        return 0

    subscribers = list(
        (
            await state.scalars(
                select(CatalogSubscription.user_id).where(
                    CatalogSubscription.entry_id == release.entry_id,
                    CatalogSubscription.notify_enabled.is_(True),
                )
            )
        ).all()
    )
    if not subscribers:
        return 0

    title = f"《{entry.title}》发布了新版本 {release.title}"
    body = release.release_notes or ""
    notified = 0
    for user_id in subscribers:
        existing = await state.scalar(
            select(CatalogReleaseNotification.id).where(
                CatalogReleaseNotification.release_id == release.release_id,
                CatalogReleaseNotification.user_id == user_id,
            )
        )
        if existing is not None:
            continue
        async with state.begin_nested():
            notification_id = await create_user_notification(
                state,
                user_id=user_id,
                title=title,
                body=body,
                level="info",
                source="catalog_release",
                enabled=True,
                published_at=utcnow(),
            )
            state.add(
                CatalogReleaseNotification(
                    release_id=release.release_id,
                    user_id=user_id,
                    notification_id=notification_id,
                )
            )
            await state.flush()
        notified += 1
    return notified


__all__ = ["notify_release_subscribers"]
