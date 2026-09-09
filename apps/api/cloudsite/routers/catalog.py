"""Authenticated-user reads for published Catalog entries."""
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from ..catalog_schemas import CatalogEntryDetail, CatalogEntryListOutput
from ..models import CatalogAsset, CatalogEntry, CatalogRelease
from .admin.catalog import _build_entry_detail, _entry_to_summary
from ..services.catalog_views import (
    catalog_asset_view,
    catalog_entry_view,
    catalog_release_view,
    published_catalog_page,
)
from ..services.catalog_search import search_published_catalog

router = APIRouter()


def _catalog_service():
    from ..services import catalog  # noqa: PLC0415

    return catalog


def _not_found() -> HTTPException:
    return HTTPException(
        404,
        {"code": "CATALOG_ENTRY_NOT_FOUND", "message": "Catalog entry not found"},
    )


@router.get("/api/catalog", response_model=CatalogEntryListOutput)
async def public_catalog_list(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    from ..main import StateSession

    service = _catalog_service()
    async with StateSession() as state:
        entries = await service.list_catalog_entries(
            state,
            status="published",
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        total = int(
            await state.scalar(
                select(func.count())
                .select_from(CatalogEntry)
                .where(CatalogEntry.status == "published")
            )
            or 0
        )
        return CatalogEntryListOutput(
            items=[_entry_to_summary(entry) for entry in entries],
            page=page,
            page_size=page_size,
            total=total,
            total_pages=max(1, (total + page_size - 1) // page_size),
        )


@router.get("/api/catalog/entries")
async def catalog_entries(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=100),
    content_type: str | None = None,
    tag: str | None = None,
):
    from ..main import IndexSession, StateSession

    async with StateSession() as state, IndexSession() as index:
        return await published_catalog_page(
            state,
            index,
            page=page,
            page_size=page_size,
            content_type=content_type,
            tag=tag,
        )


@router.get("/api/catalog/search")
async def catalog_search(
    q: str = "",
    content_type: str | None = Query(default=None, alias="type"),
    tag: str | None = None,
    platform: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=100),
):
    from ..main import IndexSession, StateSession

    try:
        async with StateSession() as state, IndexSession() as index:
            return await search_published_catalog(
                state,
                index,
                query=q,
                page=page,
                page_size=page_size,
                content_type=content_type,
                tag=tag,
                platform=platform,
            )
    except ValueError as exc:
        raise HTTPException(
            400,
            {"code": "CATALOG_SEARCH_INVALID", "message": str(exc)},
        ) from exc


@router.get("/api/catalog/entries/{entry_id}")
async def catalog_entry(entry_id: str):
    from ..main import IndexSession, StateSession

    async with StateSession() as state, IndexSession() as index:
        entry = await state.get(CatalogEntry, entry_id)
        if entry is None or entry.status != "published":
            raise _not_found()
        result = await catalog_entry_view(state, index, entry, public=True)
        if result["availability"] != "available":
            raise _not_found()
        return result


@router.get("/api/catalog/releases/{release_id}")
async def catalog_release(release_id: str):
    from ..main import IndexSession, StateSession

    async with StateSession() as state, IndexSession() as index:
        release = await state.get(CatalogRelease, release_id)
        if release is None or release.status != "published":
            raise HTTPException(404, {"code": "CATALOG_RELEASE_NOT_FOUND", "message": "Catalog release not found"})
        entry = await state.get(CatalogEntry, release.entry_id)
        if entry is None or entry.status != "published":
            raise HTTPException(404, {"code": "CATALOG_RELEASE_NOT_FOUND", "message": "Catalog release not found"})
        result = await catalog_release_view(state, index, release, public=True)
        if not any(asset["availability"] == "available" for asset in result["assets"]):
            raise HTTPException(404, {"code": "CATALOG_RELEASE_NOT_FOUND", "message": "Catalog release not found"})
        return result


@router.get("/api/catalog/assets/{asset_id}")
async def catalog_asset(asset_id: str):
    from ..main import IndexSession, StateSession

    async with StateSession() as state, IndexSession() as index:
        asset = await state.get(CatalogAsset, asset_id)
        if asset is None or asset.status != "active":
            raise HTTPException(404, {"code": "CATALOG_ASSET_NOT_FOUND", "message": "Catalog asset not found"})
        release = await state.get(CatalogRelease, asset.release_id)
        entry = await state.get(CatalogEntry, release.entry_id) if release is not None else None
        if release is None or release.status != "published" or entry is None or entry.status != "published":
            raise HTTPException(404, {"code": "CATALOG_ASSET_NOT_FOUND", "message": "Catalog asset not found"})
        result = await catalog_asset_view(
            state, index, asset, content_type=entry.content_type, public=True
        )
        if result["availability"] != "available":
            raise HTTPException(404, {"code": "CATALOG_ASSET_NOT_FOUND", "message": "Catalog asset not found"})
        return result


@router.get("/api/catalog/tags")
async def catalog_tags():
    from ..main import IndexSession, StateSession

    async with StateSession() as state, IndexSession() as index:
        page = await published_catalog_page(
            state, index, page=1, page_size=10000
        )
        tags: dict[str, dict] = {}
        for entry in page["items"]:
            for tag in entry["tags"]:
                tags[tag["tag_id"]] = tag
        return {"items": sorted(tags.values(), key=lambda item: item["slug"])}


@router.get("/api/catalog/{entry_id}", response_model=CatalogEntryDetail)
async def public_catalog_detail(entry_id: str):
    from ..main import IndexSession, StateSession

    service = _catalog_service()
    async with StateSession() as state, IndexSession() as index:
        try:
            entry = await service.get_catalog_entry(state, entry_id)
        except service.CatalogEntryNotFound as exc:
            raise _not_found() from exc
        if entry.status != "published":
            raise _not_found()
        return await _build_entry_detail(state, index, entry, published_only=True)
