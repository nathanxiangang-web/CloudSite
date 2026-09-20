"""Catalog summaries for the generic Browse surface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure.models import CatalogEntry


@dataclass(frozen=True, slots=True)
class BrowseCatalogEntryView:
    entry_id: str
    title: str
    summary: str
    content_type: str
    slug: str
    cover_resource_id: str | None
    featured: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "title": self.title,
            "summary": self.summary,
            "content_type": self.content_type,
            "slug": self.slug,
            "cover_resource_id": self.cover_resource_id,
            "featured": self.featured,
        }


async def published_browse_entries(
    state: AsyncSession,
    *,
    content_type: str | None = None,
    limit: int = 20,
) -> list[BrowseCatalogEntryView]:
    stmt = select(CatalogEntry).where(CatalogEntry.status == "published")
    if content_type:
        stmt = stmt.where(CatalogEntry.content_type == content_type)
    rows = list(
        (
            await state.scalars(
                stmt.order_by(
                    CatalogEntry.sort_order,
                    desc(CatalogEntry.published_at),
                ).limit(max(int(limit), 0))
            )
        ).all()
    )
    return [
        BrowseCatalogEntryView(
            entry_id=row.entry_id,
            title=row.title,
            summary=row.summary,
            content_type=row.content_type,
            slug=row.slug,
            cover_resource_id=row.cover_resource_id,
            featured=bool(row.featured),
        )
        for row in rows
    ]


async def featured_cover_resource_ids(
    state: AsyncSession,
    *,
    limit: int,
) -> list[str]:
    """Published featured cover ids for Home popular-resource composition."""

    rows = list(
        (
            await state.scalars(
                select(CatalogEntry)
                .where(
                    CatalogEntry.featured.is_(True),
                    CatalogEntry.status == "published",
                )
                .order_by(desc(CatalogEntry.published_at))
                .limit(max(int(limit), 0))
            )
        ).all()
    )
    return [
        row.cover_resource_id
        for row in rows
        if row.cover_resource_id
    ]


__all__ = [
    "BrowseCatalogEntryView",
    "published_browse_entries",
    "featured_cover_resource_ids",
]
