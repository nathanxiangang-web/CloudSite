"""Admin Catalog projections and orchestration.

This module is the persistence boundary for the admin HTTP surface. It may use
Catalog-owned ORM models and Resources/Providers contracts; routers receive
only dictionaries and scalar identifiers.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...providers.contracts.public import enabled_root_ids
from ...resources.contracts.public import resource_queries
from ..infrastructure.models import (
    CatalogAsset,
    CatalogEntry,
    CatalogLocation,
    CatalogRelease,
)
from .catalog_entry import (
    get_catalog_entry,
    list_catalog_entries,
    count_catalog_entries,
)
from .catalog_release import (
    CatalogAssetNotFound,
    attach_catalog_location,
    get_catalog_asset,
    get_catalog_release,
    list_catalog_assets,
    list_catalog_locations,
    list_catalog_releases,
)
from .public_queries import (
    catalog_asset_view,
    catalog_entry_view,
    catalog_release_view,
)


def _entry_summary(entry: CatalogEntry) -> dict:
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


def _total_pages(total: int, page_size: int) -> int:
    return max(1, (total + page_size - 1) // page_size)


async def admin_entry_summary_page(
    state: AsyncSession,
    *,
    page: int,
    page_size: int,
) -> dict:
    entries = await list_catalog_entries(
        state,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    total = await count_catalog_entries(state)
    return {
        "items": [_entry_summary(entry) for entry in entries],
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": _total_pages(total, page_size),
    }


async def admin_entry_view_page(
    state: AsyncSession,
    index: AsyncSession,
    *,
    page: int,
    page_size: int,
) -> dict:
    entries = await list_catalog_entries(
        state,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    total = await count_catalog_entries(state)
    return {
        "items": [
            await catalog_entry_view(
                state,
                index,
                entry,
                public=False,
            )
            for entry in entries
        ],
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": _total_pages(total, page_size),
    }


async def admin_entry_view(
    state: AsyncSession,
    index: AsyncSession,
    entry_id: str,
) -> dict:
    entry = await get_catalog_entry(state, entry_id)
    return await catalog_entry_view(
        state,
        index,
        entry,
        public=False,
    )


async def _legacy_location_summary(
    index: AsyncSession,
    *,
    location: CatalogLocation,
    asset: CatalogAsset,
    roots: set[int],
    content_type: str,
) -> dict:
    resource = await resource_queries(index).catalog_resource(
        resource_id=location.resource_id,
    )
    available = bool(
        asset.status == "active"
        and location.status == "active"
        and resource is not None
        and resource.status == "active"
        and resource.root_mapping_id is not None
        and resource.root_mapping_id in roots
        and resource.content_type == content_type
    )
    return {
        "location_id": location.location_id,
        "asset_id": location.asset_id,
        "display_name": asset.display_name,
        "sort_order": asset.sort_order,
        "available": available,
        "content_type": (
            resource.content_type if resource is not None else ""
        ),
        "extension": resource.extension if resource is not None else "",
        "size": (resource.size or 0) if resource is not None else 0,
    }


async def admin_legacy_entry_detail(
    state: AsyncSession,
    index: AsyncSession,
    entry_id: str,
    *,
    published_only: bool,
) -> dict:
    entry = await get_catalog_entry(state, entry_id)
    roots = await enabled_root_ids(state)
    releases = list(
        (
            await state.scalars(
                select(CatalogRelease).where(
                    CatalogRelease.entry_id == entry.entry_id
                )
            )
        ).all()
    )
    locations: list[dict] = []
    for release in releases:
        if published_only and release.status != "published":
            continue
        assets = list(
            (
                await state.scalars(
                    select(CatalogAsset).where(
                        CatalogAsset.release_id == release.release_id
                    )
                )
            ).all()
        )
        for asset in assets:
            if published_only and asset.status != "active":
                continue
            rows = list(
                (
                    await state.scalars(
                        select(CatalogLocation).where(
                            CatalogLocation.asset_id == asset.asset_id
                        )
                    )
                ).all()
            )
            for location in rows:
                summary = await _legacy_location_summary(
                    index,
                    location=location,
                    asset=asset,
                    roots=roots,
                    content_type=entry.content_type,
                )
                if published_only and not summary["available"]:
                    continue
                locations.append(summary)
    return {
        **_entry_summary(entry),
        "description": entry.description,
        "locations": locations,
    }


async def admin_release_view(
    state: AsyncSession,
    index: AsyncSession,
    release_id: str,
) -> dict:
    release = await get_catalog_release(state, release_id)
    return await catalog_release_view(
        state,
        index,
        release,
        public=False,
    )


async def admin_release_views(
    state: AsyncSession,
    index: AsyncSession,
    entry_id: str,
) -> list[dict]:
    await get_catalog_entry(state, entry_id)
    releases = await list_catalog_releases(state, entry_id)
    return [
        await catalog_release_view(
            state,
            index,
            release,
            public=False,
        )
        for release in releases
    ]


async def _asset_content_type(
    state: AsyncSession,
    asset: CatalogAsset,
) -> str:
    release = await state.get(CatalogRelease, asset.release_id)
    if release is None:
        return "file"
    entry = await state.get(CatalogEntry, release.entry_id)
    return entry.content_type if entry is not None else "file"


async def admin_asset_view(
    state: AsyncSession,
    index: AsyncSession,
    asset_id: str,
) -> dict:
    asset = await get_catalog_asset(state, asset_id)
    return await catalog_asset_view(
        state,
        index,
        asset,
        content_type=await _asset_content_type(state, asset),
        public=False,
    )


async def admin_asset_views(
    state: AsyncSession,
    index: AsyncSession,
    release_id: str,
) -> list[dict]:
    release = await get_catalog_release(state, release_id)
    assets = await list_catalog_assets(state, release_id)
    entry = await state.get(CatalogEntry, release.entry_id)
    content_type = entry.content_type if entry is not None else "file"
    return [
        await catalog_asset_view(
            state,
            index,
            asset,
            content_type=content_type,
            public=False,
        )
        for asset in assets
    ]


async def admin_location_view(
    state: AsyncSession,
    index: AsyncSession,
    location: CatalogLocation,
    *,
    content_type: str,
) -> dict:
    roots = await enabled_root_ids(state)
    resource = await resource_queries(index).catalog_resource(
        resource_id=location.resource_id,
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
        "asset_id": location.asset_id,
        "resource_id": location.resource_id,
        "root_mapping_id": location.root_mapping_id,
        "label": location.label,
        "is_primary": location.is_primary,
        "status": location.status,
        "availability": "available" if available else "unavailable",
        "download_url": (
            f"/d/{location.resource_id}" if available else ""
        ),
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
        "created_at": location.created_at,
        "updated_at": location.updated_at,
    }


async def admin_location_views(
    state: AsyncSession,
    index: AsyncSession,
    asset_id: str,
) -> list[dict]:
    asset = await get_catalog_asset(state, asset_id)
    locations = await list_catalog_locations(state, asset_id)
    content_type = await _asset_content_type(state, asset)
    return [
        await admin_location_view(
            state,
            index,
            location,
            content_type=content_type,
        )
        for location in locations
    ]


async def admin_attach_entry_location(
    state: AsyncSession,
    index: AsyncSession,
    *,
    entry_id: str,
    asset_id: str,
    resource_id: str,
    label: str,
    is_primary: bool,
    actor: str,
) -> dict:
    entry = await get_catalog_entry(state, entry_id)
    asset = await get_catalog_asset(state, asset_id)
    release = await get_catalog_release(state, asset.release_id)
    if release.entry_id != entry.entry_id:
        raise CatalogAssetNotFound(asset_id)
    result = await attach_catalog_location(
        state,
        index,
        asset_id=asset_id,
        resource_id=resource_id,
        label=label,
        is_primary=is_primary,
        actor=actor,
    )
    roots = await enabled_root_ids(state)
    return await _legacy_location_summary(
        index,
        location=result.location,
        asset=asset,
        roots=roots,
        content_type=entry.content_type,
    )


async def admin_location_view_for_asset(
    state: AsyncSession,
    index: AsyncSession,
    *,
    asset_id: str,
    location: CatalogLocation,
) -> dict:
    asset = await get_catalog_asset(state, asset_id)
    return await admin_location_view(
        state,
        index,
        location,
        content_type=await _asset_content_type(state, asset),
    )


__all__ = [
    "admin_entry_summary_page",
    "admin_entry_view_page",
    "admin_entry_view",
    "admin_legacy_entry_detail",
    "admin_release_view",
    "admin_release_views",
    "admin_asset_view",
    "admin_asset_views",
    "admin_location_view",
    "admin_location_views",
    "admin_attach_entry_location",
    "admin_location_view_for_asset",
]
