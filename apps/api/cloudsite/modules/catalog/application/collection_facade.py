"""Catalog reference views consumed by Collections."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure.models import CatalogEntry


@dataclass(frozen=True, slots=True)
class CatalogCollectionEntryView:
    entry_id: str
    title: str
    summary: str
    content_type: str
    cover_resource_id: str | None
    status: str


async def collection_entry_references(
    state: AsyncSession,
    *,
    entry_ids: list[str],
    published_only: bool = False,
) -> dict[str, CatalogCollectionEntryView]:
    ids = list(dict.fromkeys(entry_ids))
    if not ids:
        return {}
    stmt = select(CatalogEntry).where(CatalogEntry.entry_id.in_(ids))
    if published_only:
        stmt = stmt.where(CatalogEntry.status == "published")
    rows = list((await state.scalars(stmt)).all())
    return {
        row.entry_id: CatalogCollectionEntryView(
            entry_id=row.entry_id,
            title=row.title,
            summary=row.summary,
            content_type=row.content_type,
            cover_resource_id=row.cover_resource_id,
            status=row.status,
        )
        for row in rows
    }


__all__ = ["CatalogCollectionEntryView", "collection_entry_references"]
