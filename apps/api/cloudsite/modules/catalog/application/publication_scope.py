"""Catalog publication visibility and public DTO boundary."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....platform.observability import write_operation_log
from ..infrastructure.models import CatalogEntry


class CatalogPublicationError(RuntimeError):
    pass


class CatalogPublicationNotFound(CatalogPublicationError):
    pass


class CatalogPublicationNotPublic(CatalogPublicationError):
    pass


def is_publicly_visible(entry: CatalogEntry) -> bool:
    return bool(entry.publicly_visible) and entry.status == "published"


def public_entry_dto(entry: CatalogEntry) -> dict[str, Any]:
    return {
        "entry_id": entry.entry_id,
        "title": entry.title,
        "summary": entry.summary or "",
        "description": entry.description or "",
        "content_type": entry.content_type,
        "slug": entry.slug,
        "published_at": (
            entry.published_at.isoformat()
            if entry.published_at
            else None
        ),
        "publicly_visible": True,
    }


def publication_scope_item(entry: CatalogEntry) -> dict[str, Any]:
    return {
        "entry_id": entry.entry_id,
        "title": entry.title,
        "content_type": entry.content_type,
        "status": entry.status,
        "publicly_visible": bool(entry.publicly_visible),
        "published_at": (
            entry.published_at.isoformat()
            if entry.published_at
            else None
        ),
    }


async def list_publication_scope_entries(
    state: AsyncSession,
) -> list[dict[str, Any]]:
    rows = list(
        (
            await state.scalars(
                select(CatalogEntry).order_by(
                    CatalogEntry.sort_order,
                    CatalogEntry.title,
                )
            )
        ).all()
    )
    return [publication_scope_item(row) for row in rows]


async def update_publication_scope(
    state: AsyncSession,
    *,
    entry_id: str,
    publicly_visible: bool,
) -> dict[str, Any]:
    entry = await state.get(CatalogEntry, entry_id)
    if entry is None:
        raise CatalogPublicationNotFound(entry_id)

    entry.publicly_visible = bool(publicly_visible)
    await write_operation_log(
        state,
        level="INFO",
        module="publication_scope",
        action="publication_scope_updated",
        message=(
            f"条目 {entry_id} 公开范围设为 "
            f"{'公开' if publicly_visible else '登录可见'}"
        ),
    )
    await state.commit()

    if not publicly_visible:
        invalidate_sitemap_cache()

    return {
        "ok": True,
        "entry_id": entry_id,
        "publicly_visible": bool(publicly_visible),
    }


async def public_catalog_entry(
    state: AsyncSession,
    *,
    entry_id: str,
) -> dict[str, Any]:
    entry = await state.get(CatalogEntry, entry_id)
    if (
        entry is None
        or not entry.publicly_visible
        or entry.status != "published"
    ):
        raise CatalogPublicationNotPublic(entry_id)
    return public_entry_dto(entry)


async def list_public_entries(
    state: AsyncSession,
) -> list[CatalogEntry]:
    rows = await state.scalars(
        select(CatalogEntry)
        .where(
            CatalogEntry.publicly_visible.is_(True),
            CatalogEntry.status == "published",
        )
        .order_by(CatalogEntry.sort_order, CatalogEntry.title)
    )
    return list(rows.all())


async def set_publicly_visible(
    state: AsyncSession,
    entry_id: str,
    visible: bool,
) -> CatalogEntry | None:
    """Legacy compatibility helper; does not commit or write audit logs."""

    entry = await state.get(CatalogEntry, entry_id)
    if entry is None:
        return None
    entry.publicly_visible = bool(visible)
    return entry


def sitemap_entry_url(entry: CatalogEntry, base_url: str) -> str:
    return f"{base_url.rstrip('/')}/catalog/{entry.entry_id}"


def build_sitemap_xml(
    entries: list[CatalogEntry],
    base_url: str,
) -> str:
    urls: list[str] = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for entry in entries:
        if not is_publicly_visible(entry):
            continue
        loc = sitemap_entry_url(entry, base_url)
        lastmod = (
            entry.published_at.strftime("%Y-%m-%d")
            if entry.published_at
            else now
        )
        urls.append(
            "  <url>\n"
            f"    <loc>{loc}</loc>\n"
            f"    <lastmod>{lastmod}</lastmod>\n"
            f"    <changefreq>weekly</changefreq>\n"
            "    <priority>0.8</priority>\n"
            "  </url>"
        )
    body = "\n".join(urls)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{body}\n"
        "</urlset>"
    )


_sitemap_cache: dict[str, object] = {
    "data": None,
    "fetched_at": 0.0,
}


def invalidate_sitemap_cache() -> None:
    _sitemap_cache["data"] = None
    _sitemap_cache["fetched_at"] = 0.0


__all__ = [
    "CatalogPublicationError",
    "CatalogPublicationNotFound",
    "CatalogPublicationNotPublic",
    "is_publicly_visible",
    "public_entry_dto",
    "publication_scope_item",
    "list_publication_scope_entries",
    "update_publication_scope",
    "public_catalog_entry",
    "list_public_entries",
    "set_publicly_visible",
    "sitemap_entry_url",
    "build_sitemap_xml",
    "invalidate_sitemap_cache",
]
