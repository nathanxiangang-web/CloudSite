"""Scope-safe basic search for published Catalog entries.

This first D1 slice deliberately keeps the existing file/folder FTS endpoint
unchanged.  Catalog metadata is searched from state.db and every candidate is
projected through the live public Catalog view before it can be returned.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    CatalogAsset,
    CatalogEntry,
    CatalogRelease,
    CatalogTag,
    CatalogTagAssignment,
)
from .catalog_views import catalog_entry_view


def normalize_catalog_query(value: str) -> str:
    return " ".join(value.strip().split())


def _contains(haystack: str, needle: str) -> bool:
    return needle in haystack.casefold()


async def search_published_catalog(
    state: AsyncSession,
    index: AsyncSession,
    *,
    query: str,
    page: int = 1,
    page_size: int = 24,
    content_type: str | None = None,
    tag: str | None = None,
    platform: str | None = None,
) -> dict[str, Any]:
    """Search published entries and fail closed against the live file scope."""
    normalized = normalize_catalog_query(query)
    if not normalized:
        raise ValueError("catalog search query is empty")
    if len(normalized) > 200:
        raise ValueError("catalog search query is too long")
    if page < 1 or page_size < 1 or page_size > 100:
        raise ValueError("invalid catalog search pagination")

    entry_stmt = select(CatalogEntry).where(CatalogEntry.status == "published")
    if content_type:
        entry_stmt = entry_stmt.where(CatalogEntry.content_type == content_type)
    entries = list((await state.scalars(entry_stmt)).all())
    if not entries:
        return _page([], normalized, page, page_size, content_type, tag, platform)

    entry_ids = [entry.entry_id for entry in entries]
    releases = list(
        (
            await state.scalars(
                select(CatalogRelease).where(CatalogRelease.entry_id.in_(entry_ids))
            )
        ).all()
    )
    releases_by_entry: dict[str, list[CatalogRelease]] = defaultdict(list)
    for release in releases:
        releases_by_entry[release.entry_id].append(release)

    release_ids = [release.release_id for release in releases]
    assets = (
        list(
            (
                await state.scalars(
                    select(CatalogAsset).where(CatalogAsset.release_id.in_(release_ids))
                )
            ).all()
        )
        if release_ids
        else []
    )
    assets_by_release: dict[str, list[CatalogAsset]] = defaultdict(list)
    for asset in assets:
        assets_by_release[asset.release_id].append(asset)

    tag_rows = list(
        (
            await state.execute(
                select(CatalogTagAssignment.target_id, CatalogTag)
                .join(CatalogTag, CatalogTag.tag_id == CatalogTagAssignment.tag_id)
                .where(
                    CatalogTagAssignment.target_type == "entry",
                    CatalogTagAssignment.target_id.in_(entry_ids),
                )
            )
        ).all()
    )
    tags_by_entry: dict[str, list[CatalogTag]] = defaultdict(list)
    for entry_id, tag_row in tag_rows:
        tags_by_entry[entry_id].append(tag_row)

    needle = normalized.casefold()
    tag_filter = tag.casefold() if tag else None
    platform_filter = platform.casefold() if platform else None
    ranked: list[tuple[int, CatalogEntry]] = []
    for entry in entries:
        entry_tags = tags_by_entry[entry.entry_id]
        entry_releases = releases_by_entry[entry.entry_id]
        entry_assets = [
            asset
            for release in entry_releases
            for asset in assets_by_release[release.release_id]
        ]
        if tag_filter and not any(
            item.slug.casefold() == tag_filter for item in entry_tags
        ):
            continue
        if platform_filter and not any(
            (asset.platform or "unknown").casefold() == platform_filter
            for asset in entry_assets
        ):
            continue

        title = entry.title.casefold()
        metadata = " ".join(
            [
                entry.slug,
                entry.summary,
                entry.description,
                *(item.slug for item in entry_tags),
                *(item.display_name for item in entry_tags),
                *(release.slug for release in entry_releases),
                *(release.title for release in entry_releases),
                *(release.channel or "unknown" for release in entry_releases),
                *(asset.display_name for asset in entry_assets),
                *(asset.platform or "unknown" for asset in entry_assets),
                *(asset.architecture or "unknown" for asset in entry_assets),
                *(asset.package_type or "unknown" for asset in entry_assets),
            ]
        )
        if title == needle:
            rank = 400
        elif title.startswith(needle):
            rank = 300
        elif needle in title:
            rank = 200
        elif _contains(metadata, needle):
            rank = 100
        else:
            continue
        ranked.append((rank, entry))

    ranked.sort(key=lambda item: (-item[0], item[1].sort_order, item[1].title.casefold()))
    visible: list[dict[str, Any]] = []
    for rank, entry in ranked:
        view = await catalog_entry_view(state, index, entry, public=True)
        if view["availability"] != "available":
            continue
        if platform_filter and not any(
            asset["availability"] == "available"
            and asset["platform"].casefold() == platform_filter
            for release in view["releases"]
            for asset in release["assets"]
        ):
            continue
        view["match_type"] = {
            400: "exact",
            300: "prefix",
            200: "title",
            100: "metadata",
        }[rank]
        visible.append(view)
    return _page(visible, normalized, page, page_size, content_type, tag, platform)


def _page(
    rows: list[dict[str, Any]],
    query: str,
    page: int,
    page_size: int,
    content_type: str | None,
    tag: str | None,
    platform: str | None,
) -> dict[str, Any]:
    total = len(rows)
    start = (page - 1) * page_size
    return {
        "query": query,
        "filters": {
            "content_type": content_type,
            "tag": tag,
            "platform": platform,
        },
        "items": rows[start : start + page_size],
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": (total + page_size - 1) // page_size if total else 0,
    }
