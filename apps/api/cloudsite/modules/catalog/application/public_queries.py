"""Public Catalog read projections owned by the Catalog module.

These queries assemble Catalog-owned ORM state and revalidate resource
availability through Resources contracts. Routers consume only dictionaries and
IDs; no Catalog/Resource ORM crosses the HTTP boundary.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...providers.contracts.public import enabled_root_ids
from ...resources.contracts.public import resource_queries
from ..infrastructure.models import (
    CatalogAsset,
    CatalogEntry,
    CatalogLocation,
    CatalogRelation,
    CatalogRelease,
    CatalogTag,
    CatalogTagAssignment,
)


class CatalogViewNotFound(Exception):
    pass


async def _location_view(
    index: AsyncSession,
    location: CatalogLocation,
    *,
    roots: set[int],
    content_type: str,
) -> dict:
    resource = await resource_queries(index).catalog_resource(
        resource_id=location.resource_id
    )
    available = bool(
        location.status == "active"
        and resource is not None
        and resource.status == "active"
        and resource.root_mapping_id is not None
        and resource.root_mapping_id in roots
        and resource.content_type == content_type
    )
    return {
        "location_id": location.location_id,
        "resource_id": location.resource_id,
        "root_mapping_id": location.root_mapping_id,
        "label": location.label,
        "is_primary": location.is_primary,
        "status": location.status,
        "availability": "available" if available else "unavailable",
        "download_url": f"/d/{location.resource_id}" if available else "",
        "resource": (
            {
                "id": resource.id,
                "name": resource.name,
                "extension": resource.extension,
                "size": resource.size or 0,
                "content_type": resource.content_type,
            }
            if available and resource is not None
            else None
        ),
    }


async def catalog_asset_view(
    state: AsyncSession,
    index: AsyncSession,
    asset: CatalogAsset,
    *,
    content_type: str,
    public: bool,
    roots: set[int] | None = None,
) -> dict:
    active_roots = roots if roots is not None else await enabled_root_ids(state)
    locations = list(
        (
            await state.scalars(
                select(CatalogLocation)
                .where(CatalogLocation.asset_id == asset.asset_id)
                .order_by(
                    CatalogLocation.is_primary.desc(),
                    CatalogLocation.created_at,
                )
            )
        ).all()
    )
    location_views = [
        await _location_view(
            index,
            location,
            roots=active_roots,
            content_type=content_type,
        )
        for location in locations
    ]
    if public:
        location_views = [
            item for item in location_views
            if item["availability"] == "available"
        ]
    available = asset.status == "active" and bool(location_views)
    return {
        "asset_id": asset.asset_id,
        "slug": asset.slug,
        "display_name": asset.display_name,
        "platform": asset.platform or "unknown",
        "architecture": getattr(asset, "architecture", "unknown") or "unknown",
        "package_type": getattr(asset, "package_type", "unknown") or "unknown",
        "language": getattr(asset, "language", "unknown") or "unknown",
        "build_label": getattr(asset, "build_label", "") or "",
        "kind": asset.kind,
        "checksum": asset.checksum,
        "checksum_algorithm": asset.checksum_algorithm,
        "size": asset.size,
        "sort_order": asset.sort_order,
        "status": asset.status,
        "availability": "available" if available else "unavailable",
        "location_count": len(location_views),
        "locations": location_views,
    }


async def _entry_for_release(
    state: AsyncSession,
    release: CatalogRelease,
) -> CatalogEntry:
    entry = await state.get(CatalogEntry, release.entry_id)
    if entry is None:
        raise CatalogViewNotFound(release.release_id)
    return entry


async def catalog_release_view(
    state: AsyncSession,
    index: AsyncSession,
    release: CatalogRelease,
    *,
    public: bool,
    roots: set[int] | None = None,
) -> dict:
    entry = await _entry_for_release(state, release)
    assets = list(
        (
            await state.scalars(
                select(CatalogAsset)
                .where(CatalogAsset.release_id == release.release_id)
                .order_by(CatalogAsset.sort_order, CatalogAsset.created_at)
            )
        ).all()
    )
    if public:
        assets = [asset for asset in assets if asset.status == "active"]
    asset_views = [
        await catalog_asset_view(
            state,
            index,
            asset,
            content_type=entry.content_type,
            public=public,
            roots=roots,
        )
        for asset in assets
    ]
    return {
        "release_id": release.release_id,
        "entry_id": release.entry_id,
        "slug": release.slug,
        "title": release.title,
        "release_notes": release.release_notes,
        "channel": getattr(release, "channel", "unknown") or "unknown",
        "is_recommended": bool(getattr(release, "is_recommended", False)),
        "release_date": (
            release.release_date.isoformat()
            if getattr(release, "release_date", None)
            else None
        ),
        "status": release.status,
        "sort_order": release.sort_order,
        "created_at": release.created_at,
        "updated_at": release.updated_at,
        "published_at": release.published_at,
        "assets": asset_views,
    }


async def _entry_tags(state: AsyncSession, entry_id: str) -> list[dict]:
    rows = (
        await state.execute(
            select(CatalogTag)
            .join(
                CatalogTagAssignment,
                CatalogTagAssignment.tag_id == CatalogTag.tag_id,
            )
            .where(
                CatalogTagAssignment.target_type == "entry",
                CatalogTagAssignment.target_id == entry_id,
            )
            .order_by(CatalogTag.slug)
        )
    ).scalars()
    return [
        {
            "tag_id": tag.tag_id,
            "slug": tag.slug,
            "display_name": tag.display_name,
        }
        for tag in rows.all()
    ]


async def _entry_relations(
    state: AsyncSession,
    entry_id: str,
    *,
    public: bool,
) -> list[dict]:
    rows = list(
        (
            await state.scalars(
                select(CatalogRelation)
                .where(CatalogRelation.from_entry_id == entry_id)
                .order_by(CatalogRelation.created_at)
            )
        ).all()
    )
    result: list[dict] = []
    for relation in rows:
        target = await state.get(CatalogEntry, relation.to_entry_id)
        if target is None or (public and target.status != "published"):
            continue
        result.append(
            {
                "relation_id": relation.relation_id,
                "to_entry_id": target.entry_id,
                "to_title": target.title,
                "relation_type": relation.relation_type,
                "note": relation.note,
            }
        )
    return result


async def catalog_entry_view(
    state: AsyncSession,
    index: AsyncSession,
    entry: CatalogEntry,
    *,
    public: bool,
) -> dict:
    roots = await enabled_root_ids(state)
    releases = list(
        (
            await state.scalars(
                select(CatalogRelease)
                .where(CatalogRelease.entry_id == entry.entry_id)
                .order_by(CatalogRelease.sort_order, CatalogRelease.created_at)
            )
        ).all()
    )
    if public:
        releases = [
            release for release in releases
            if release.status == "published"
        ]
    release_views = [
        await catalog_release_view(
            state,
            index,
            release,
            public=public,
            roots=roots,
        )
        for release in releases
    ]
    available = any(
        asset["availability"] == "available"
        for release in release_views
        for asset in release["assets"]
    )
    return {
        "entry_id": entry.entry_id,
        "slug": entry.slug,
        "title": entry.title,
        "content_type": entry.content_type,
        "summary": entry.summary,
        "description": entry.description,
        "cover_resource_id": entry.cover_resource_id,
        "status": entry.status,
        "revision": entry.revision,
        "sort_order": entry.sort_order,
        "availability": "available" if available else "unavailable",
        "tags": await _entry_tags(state, entry.entry_id),
        "relations": await _entry_relations(
            state,
            entry.entry_id,
            public=public,
        ),
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
        "published_at": entry.published_at,
        "releases": release_views,
    }


def _legacy_entry_summary(entry: CatalogEntry) -> dict:
    return {
        "entry_id": entry.entry_id,
        "title": entry.title,
        "summary": entry.summary,
        "content_type": entry.content_type,
        "status": entry.status,
        "revision": entry.revision,
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
        "published_at": entry.published_at,
    }


async def published_catalog_summary_page(
    state: AsyncSession,
    *,
    page: int,
    page_size: int,
) -> dict:
    """Legacy-compatible public summary page without router ORM access."""

    total = int(
        await state.scalar(
            select(func.count())
            .select_from(CatalogEntry)
            .where(CatalogEntry.status == "published")
        )
        or 0
    )
    entries = list(
        (
            await state.scalars(
                select(CatalogEntry)
                .where(CatalogEntry.status == "published")
                .order_by(
                    CatalogEntry.sort_order,
                    CatalogEntry.created_at,
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return {
        "items": [_legacy_entry_summary(entry) for entry in entries],
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": max(
            1,
            (total + page_size - 1) // page_size,
        ),
    }


async def public_catalog_legacy_detail(
    state: AsyncSession,
    index: AsyncSession,
    entry_id: str,
) -> dict | None:
    """Legacy CatalogEntryDetail projection built from module-owned views."""

    rich = await public_catalog_entry_view(
        state,
        index,
        entry_id,
    )
    if rich is None:
        return None

    locations: list[dict] = []
    for release in rich["releases"]:
        for asset in release["assets"]:
            for location in asset["locations"]:
                resource = location.get("resource")
                locations.append(
                    {
                        "location_id": location["location_id"],
                        "asset_id": asset["asset_id"],
                        "display_name": asset["display_name"],
                        "sort_order": int(
                            asset.get("sort_order") or 0
                        ),
                        "available": True,
                        "content_type": (
                            resource.get("content_type", "")
                            if resource
                            else ""
                        ),
                        "extension": (
                            resource.get("extension", "")
                            if resource
                            else ""
                        ),
                        "size": (
                            int(resource.get("size") or 0)
                            if resource
                            else 0
                        ),
                    }
                )

    return {
        "entry_id": rich["entry_id"],
        "title": rich["title"],
        "summary": rich["summary"],
        "content_type": rich["content_type"],
        "status": rich["status"],
        "revision": rich["revision"],
        "created_at": rich["created_at"],
        "updated_at": rich["updated_at"],
        "published_at": rich["published_at"],
        "description": rich["description"],
        "locations": locations,
    }


async def published_catalog_page(
    state: AsyncSession,
    index: AsyncSession,
    *,
    page: int,
    page_size: int,
    content_type: str | None = None,
    tag: str | None = None,
) -> dict:
    stmt = select(CatalogEntry).where(CatalogEntry.status == "published")
    if content_type:
        stmt = stmt.where(CatalogEntry.content_type == content_type)
    if tag:
        stmt = (
            stmt.join(
                CatalogTagAssignment,
                (CatalogTagAssignment.target_type == "entry")
                & (CatalogTagAssignment.target_id == CatalogEntry.entry_id),
            )
            .join(CatalogTag, CatalogTag.tag_id == CatalogTagAssignment.tag_id)
            .where(CatalogTag.slug == tag)
        )
    entries = list(
        (
            await state.scalars(
                stmt.order_by(
                    CatalogEntry.sort_order,
                    CatalogEntry.created_at,
                )
            )
        ).unique().all()
    )
    views = [
        await catalog_entry_view(state, index, entry, public=True)
        for entry in entries
    ]
    views = [
        entry for entry in views
        if entry["availability"] == "available"
    ]
    total = len(views)
    start = (page - 1) * page_size
    return {
        "items": views[start : start + page_size],
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": max(1, (total + page_size - 1) // page_size),
    }


async def public_catalog_entry_view(
    state: AsyncSession,
    index: AsyncSession,
    entry_id: str,
) -> dict | None:
    entry = await state.get(CatalogEntry, entry_id)
    if entry is None or entry.status != "published":
        return None
    result = await catalog_entry_view(state, index, entry, public=True)
    if result["availability"] != "available":
        return None
    return result


async def public_catalog_release_view(
    state: AsyncSession,
    index: AsyncSession,
    release_id: str,
) -> dict | None:
    release = await state.get(CatalogRelease, release_id)
    if release is None or release.status != "published":
        return None
    entry = await state.get(CatalogEntry, release.entry_id)
    if entry is None or entry.status != "published":
        return None
    result = await catalog_release_view(state, index, release, public=True)
    if not any(
        asset["availability"] == "available"
        for asset in result["assets"]
    ):
        return None
    return result


async def public_catalog_asset_view(
    state: AsyncSession,
    index: AsyncSession,
    asset_id: str,
) -> dict | None:
    asset = await state.get(CatalogAsset, asset_id)
    if asset is None or asset.status != "active":
        return None
    release = await state.get(CatalogRelease, asset.release_id)
    if release is None or release.status != "published":
        return None
    entry = await state.get(CatalogEntry, release.entry_id)
    if entry is None or entry.status != "published":
        return None
    result = await catalog_asset_view(
        state,
        index,
        asset,
        content_type=entry.content_type,
        public=True,
    )
    if result["availability"] != "available":
        return None
    return result


__all__ = [
    "CatalogViewNotFound",
    "catalog_asset_view",
    "catalog_release_view",
    "catalog_entry_view",
    "published_catalog_page",
    "published_catalog_summary_page",
    "public_catalog_legacy_detail",
    "public_catalog_entry_view",
    "public_catalog_release_view",
    "public_catalog_asset_view",
]
