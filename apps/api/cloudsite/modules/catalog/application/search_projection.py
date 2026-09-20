"""Catalog-owned source side of the search projection boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .outbox import enqueue_catalog_search_outbox
from ..infrastructure.models import (
    CatalogAsset,
    CatalogEntry,
    CatalogRelease,
    CatalogSearchOutbox,
    CatalogTag,
    CatalogTagAssignment,
)


@dataclass(frozen=True, slots=True)
class CatalogSearchOutboxItem:
    outbox_id: str
    entry_id: str
    revision: int
    action: str


@dataclass(frozen=True, slots=True)
class CatalogSearchDocument:
    entry_id: str
    content_type: str
    title: str
    summary: str
    description: str
    aliases: str
    tags: str
    platforms: str


@dataclass(frozen=True, slots=True)
class CatalogSearchProjectionSource:
    entry_id: str
    revision: int | None
    document: CatalogSearchDocument | None


async def pending_catalog_search_outbox(
    state: AsyncSession,
    *,
    batch_limit: int = 500,
) -> list[CatalogSearchOutboxItem]:
    rows = list(
        (
            await state.scalars(
                select(CatalogSearchOutbox)
                .where(CatalogSearchOutbox.consumed_at.is_(None))
                .order_by(
                    CatalogSearchOutbox.created_at,
                    CatalogSearchOutbox.outbox_id,
                )
                .limit(batch_limit)
            )
        ).all()
    )
    return [
        CatalogSearchOutboxItem(
            outbox_id=row.outbox_id,
            entry_id=row.entry_id,
            revision=row.revision,
            action=row.action,
        )
        for row in rows
    ]


async def mark_catalog_search_outbox_consumed(
    state: AsyncSession,
    *,
    outbox_id: str,
    consumed_at: datetime,
) -> None:
    row = await state.get(CatalogSearchOutbox, outbox_id)
    if row is not None:
        row.consumed_at = consumed_at


async def catalog_search_projection_source(
    state: AsyncSession,
    *,
    entry_id: str,
) -> CatalogSearchProjectionSource:
    entry = await state.get(CatalogEntry, entry_id)
    if entry is None:
        return CatalogSearchProjectionSource(
            entry_id=entry_id,
            revision=None,
            document=None,
        )
    if entry.status != "published":
        return CatalogSearchProjectionSource(
            entry_id=entry_id,
            revision=entry.revision,
            document=None,
        )

    releases = list(
        (
            await state.scalars(
                select(CatalogRelease).where(
                    CatalogRelease.entry_id == entry.entry_id
                )
            )
        ).all()
    )
    release_ids = [release.release_id for release in releases]
    assets = (
        list(
            (
                await state.scalars(
                    select(CatalogAsset).where(
                        CatalogAsset.release_id.in_(release_ids)
                    )
                )
            ).all()
        )
        if release_ids
        else []
    )
    tag_rows = list(
        (
            await state.execute(
                select(CatalogTag.slug, CatalogTag.display_name)
                .join(
                    CatalogTagAssignment,
                    CatalogTagAssignment.tag_id == CatalogTag.tag_id,
                )
                .where(
                    CatalogTagAssignment.target_type == "entry",
                    CatalogTagAssignment.target_id == entry.entry_id,
                )
            )
        ).all()
    )

    aliases_parts = [entry.slug]
    aliases_parts.extend(release.slug for release in releases)
    aliases_parts.extend(release.title for release in releases)
    aliases_parts.extend(asset.slug for asset in assets)
    aliases_parts.extend(asset.display_name for asset in assets)

    tags_parts: list[str] = []
    for slug, display_name in tag_rows:
        tags_parts.extend((slug, display_name))

    platforms_parts: list[str] = []
    for release in releases:
        platforms_parts.append(release.channel or "unknown")
    for asset in assets:
        platforms_parts.extend(
            (
                asset.platform or "unknown",
                asset.architecture or "unknown",
                asset.package_type or "unknown",
            )
        )

    return CatalogSearchProjectionSource(
        entry_id=entry.entry_id,
        revision=entry.revision,
        document=CatalogSearchDocument(
            entry_id=entry.entry_id,
            content_type=entry.content_type,
            title=entry.title,
            summary=entry.summary or "",
            description=entry.description or "",
            aliases=" ".join(aliases_parts),
            tags=" ".join(tags_parts),
            platforms=" ".join(platforms_parts),
        ),
    )


async def prepare_catalog_search_rebuild(
    state: AsyncSession,
    *,
    consumed_at: datetime,
) -> int:
    pending_rows = list(
        (
            await state.scalars(
                select(CatalogSearchOutbox).where(
                    CatalogSearchOutbox.consumed_at.is_(None)
                )
            )
        ).all()
    )
    for row in pending_rows:
        row.consumed_at = consumed_at

    entries = list(
        (
            await state.scalars(
                select(CatalogEntry).where(
                    CatalogEntry.status == "published"
                )
            )
        ).all()
    )
    for entry in entries:
        await enqueue_catalog_search_outbox(
            state,
            entry_id=entry.entry_id,
            revision=entry.revision,
            action="upsert",
        )
    return len(entries)


__all__ = [
    "CatalogSearchDocument",
    "CatalogSearchOutboxItem",
    "CatalogSearchProjectionSource",
    "catalog_search_projection_source",
    "mark_catalog_search_outbox_consumed",
    "pending_catalog_search_outbox",
    "prepare_catalog_search_rebuild",
]
