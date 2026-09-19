"""Authenticated-user reads for published Catalog entries."""
import time

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse

from ..catalog_schemas import CatalogEntryDetail, CatalogEntryListOutput
from ..download import DownloadError, resolve_download_entry
from ..download_rate_limit import (
    check_download_rate,
    get_effective_client_ip,
    rate_limit_payload,
)
from ..services.downloads import _download_event
from ..modules.catalog.contracts import public as catalog_api
from ..modules.catalog.contracts.public import (
    public_catalog_asset_view,
    public_catalog_entry_view,
    public_catalog_release_view,
    published_catalog_page,
)
from ..modules.providers.contracts.public import enabled_root_ids, provider_runtime
from ..modules.resources.contracts.public import (
    ResourceInactiveError,
    ResourceNotAvailableError,
    ResourceNotFoundError,
    resource_queries,
)
from ..services.catalog_search import search_published_catalog

router = APIRouter()


def _catalog_service():
    return catalog_api


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

    async with StateSession() as state:
        payload = await catalog_api.admin_entry_summary_page(
            state,
            page=page,
            page_size=page_size,
            status="published",
        )
        return CatalogEntryListOutput(**payload)


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
        result = await public_catalog_entry_view(state, index, entry_id)
        if result is None:
            raise _not_found()
        return result


@router.get("/api/catalog/releases/{release_id}")
async def catalog_release(release_id: str):
    from ..main import IndexSession, StateSession

    async with StateSession() as state, IndexSession() as index:
        result = await public_catalog_release_view(state, index, release_id)
        if result is None:
            raise HTTPException(
                404,
                {"code": "CATALOG_RELEASE_NOT_FOUND", "message": "Catalog release not found"},
            )
        return result


@router.get("/api/catalog/assets/{asset_id}")
async def catalog_asset(asset_id: str):
    from ..main import IndexSession, StateSession

    async with StateSession() as state, IndexSession() as index:
        result = await public_catalog_asset_view(state, index, asset_id)
        if result is None:
            raise HTTPException(
                404,
                {"code": "CATALOG_ASSET_NOT_FOUND", "message": "Catalog asset not found"},
            )
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

    async with StateSession() as state, IndexSession() as index:
        try:
            entry = await catalog_api.get_catalog_entry(
                state,
                entry_id,
            )
        except catalog_api.CatalogEntryNotFound as exc:
            raise _not_found() from exc
        if entry.status != "published":
            raise _not_found()
        return await catalog_api.admin_legacy_entry_detail(
            state,
            index,
            entry_id,
            published_only=True,
        )


# ---- C2 Asset download signing ----

_NOT_FOUND_REASONS = {"entry_not_published", "asset_not_found", "asset_not_in_entry", "release_not_published"}


@router.post("/api/catalog/entries/{entry_id}/assets/{asset_id}/download")
async def catalog_asset_download(entry_id: str, asset_id: str, request: Request):
    from ..main import IndexSession, StateSession

    started = time.perf_counter()
    service = _catalog_service()
    async with StateSession() as state, IndexSession() as index:
        try:
            target = await service.resolve_asset_download_target(state, index, entry_id, asset_id)
        except service.CatalogAssetNotDownloadable as exc:
            if exc.reason in _NOT_FOUND_REASONS:
                raise HTTPException(404, {"code": "CATALOG_ASSET_NOT_FOUND", "message": "Catalog asset not found"}) from exc
            raise HTTPException(
                409,
                {"code": "CATALOG_ASSET_NOT_DOWNLOADABLE", "message": "asset is not downloadable", "reason": exc.reason},
            ) from exc
        except service.CatalogError as exc:
            raise _not_found() from exc

        try:
            roots = await enabled_root_ids(state)
            resource = await resource_queries(index).download_resource(
                resource_id=target.resource_id,
                enabled_root_ids=roots,
            )
        except (
            ResourceNotFoundError,
            ResourceInactiveError,
            ResourceNotAvailableError,
        ):
            await _download_event(
                state,
                target.resource_id,
                "failed",
                "DL-001",
                started,
                source="catalog",
            )
            raise HTTPException(
                409,
                {
                    "code": "CATALOG_ASSET_NOT_DOWNLOADABLE",
                    "message": "underlying resource unavailable",
                    "reason": "resource_inactive",
                },
            )

        rate = await check_download_rate(get_effective_client_ip(request))
        if not rate.allowed:
            await _download_event(state, target.resource_id, "failed", "DOWNLOAD_RATE_LIMITED", started, source="catalog")
            return JSONResponse(
                rate_limit_payload(rate),
                status_code=429,
                headers={"Retry-After": str(rate.retry_after)},
            )

        try:
            resolution = await resolve_download_entry(
                resource,
                provider_runtime(state),
            )
        except DownloadError as exc:
            await _download_event(state, target.resource_id, "failed", exc.code, started, source="catalog")
            raise HTTPException(502, {"code": exc.code, "message": "download resolution failed"}) from exc

        await _download_event(state, target.resource_id, "success", None, started, source="catalog")
        return RedirectResponse(resolution.url, status_code=302)
