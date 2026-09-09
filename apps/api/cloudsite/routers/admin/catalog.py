"""Administrator Catalog routes backed by the real application service."""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from ...catalog_schemas import (
    CatalogEntryCreateInput,
    CatalogEntryDetail,
    CatalogEntryListOutput,
    CatalogEntryPublishInput,
    CatalogEntrySummary,
    CatalogEntryUpdateInput,
    CatalogLocationBindInput,
    CatalogLocationSummary,
    CatalogPreviewOutput,
)
from ...models import CatalogAsset, CatalogEntry, CatalogLocation, CatalogRelease, Resource

router = APIRouter()


def _catalog_service():
    from ...services import catalog  # noqa: PLC0415

    return catalog


def _translate_catalog_error(exc: Exception) -> HTTPException:
    service = _catalog_service()
    if isinstance(exc, service.CatalogEntryNotFound):
        return HTTPException(404, {"code": "CATALOG_ENTRY_NOT_FOUND", "message": "Catalog entry not found"})
    if isinstance(exc, service.CatalogRevisionConflict):
        return HTTPException(409, {"code": "CATALOG_REVISION_CONFLICT", "message": str(exc)})
    if isinstance(exc, service.CatalogSlugConflict):
        return HTTPException(409, {"code": "CATALOG_SLUG_CONFLICT", "message": str(exc)})
    if isinstance(exc, service.CatalogLocationInvalid):
        return HTTPException(409, {"code": "CATALOG_LOCATION_INVALID", "message": str(exc)})
    if isinstance(exc, service.CatalogPublishValidationFailed):
        return HTTPException(
            409,
            {
                "code": "CATALOG_PUBLISH_VALIDATION_FAILED",
                "message": "Catalog entry cannot be published",
                "reasons": exc.reasons,
            },
        )
    if isinstance(exc, (service.CatalogAssetNotFound, service.CatalogReleaseNotFound)):
        return HTTPException(404, {"code": "CATALOG_OBJECT_NOT_FOUND", "message": str(exc)})
    return HTTPException(500, {"code": "CATALOG_ERROR", "message": "Catalog service error"})


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "-", title.lower()).strip("-")
    return slug or "entry"


def _entry_to_summary(entry: CatalogEntry) -> CatalogEntrySummary:
    return CatalogEntrySummary(
        entry_id=entry.entry_id,
        title=entry.title,
        summary=entry.summary,
        content_type=entry.content_type,
        status=entry.status,
        revision=entry.revision,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
        published_at=entry.published_at,
    )


def _resource_available(resource: Resource | None, roots: set[int], content_type: str) -> bool:
    return bool(
        resource is not None
        and resource.status == "active"
        and resource.root_mapping_id is not None
        and resource.root_mapping_id in roots
        and resource.content_type == content_type
    )


def _location_to_summary(
    location: CatalogLocation,
    asset: CatalogAsset,
    resource: Resource | None,
    available: bool,
) -> CatalogLocationSummary:
    return CatalogLocationSummary(
        location_id=location.location_id,
        asset_id=location.asset_id,
        display_name=asset.display_name,
        sort_order=asset.sort_order,
        available=available,
        content_type=resource.content_type if resource is not None else "",
        extension=resource.extension if resource is not None else "",
        size=(resource.size or 0) if resource is not None else 0,
    )


async def _build_entry_detail(state, index, entry: CatalogEntry, *, published_only: bool) -> CatalogEntryDetail:
    service = _catalog_service()
    roots = await service.enabled_root_ids(state)
    releases = list(
        (
            await state.scalars(
                select(CatalogRelease).where(CatalogRelease.entry_id == entry.entry_id)
            )
        ).all()
    )
    locations: list[CatalogLocationSummary] = []
    for release in releases:
        if published_only and release.status != "published":
            continue
        assets = list(
            (
                await state.scalars(
                    select(CatalogAsset).where(CatalogAsset.release_id == release.release_id)
                )
            ).all()
        )
        for asset in assets:
            if published_only and asset.status != "active":
                continue
            rows = list(
                (
                    await state.scalars(
                        select(CatalogLocation).where(CatalogLocation.asset_id == asset.asset_id)
                    )
                ).all()
            )
            for location in rows:
                resource = await index.get(Resource, location.resource_id)
                available = bool(
                    asset.status == "active"
                    and location.status == "active"
                    and _resource_available(resource, roots, entry.content_type)
                )
                if published_only and not available:
                    continue
                locations.append(_location_to_summary(location, asset, resource, available))
    return CatalogEntryDetail(
        **_entry_to_summary(entry).model_dump(),
        description=entry.description,
        locations=locations,
    )


def _total_pages(total: int, page_size: int) -> int:
    return max(1, (total + page_size - 1) // page_size)


@router.get("/api/admin/catalog", response_model=CatalogEntryListOutput)
async def admin_catalog_list(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    from ...main import StateSession

    service = _catalog_service()
    async with StateSession() as state:
        entries = await service.list_catalog_entries(
            state, limit=page_size, offset=(page - 1) * page_size
        )
        total = int(await state.scalar(select(func.count()).select_from(CatalogEntry)) or 0)
        return CatalogEntryListOutput(
            items=[_entry_to_summary(entry) for entry in entries],
            page=page,
            page_size=page_size,
            total=total,
            total_pages=_total_pages(total, page_size),
        )


@router.get("/api/admin/catalog/{entry_id}", response_model=CatalogEntryDetail)
async def admin_catalog_detail(entry_id: str):
    from ...main import IndexSession, StateSession

    service = _catalog_service()
    async with StateSession() as state, IndexSession() as index:
        try:
            entry = await service.get_catalog_entry(state, entry_id)
        except service.CatalogError as exc:
            raise _translate_catalog_error(exc) from exc
        return await _build_entry_detail(state, index, entry, published_only=False)


@router.post("/api/admin/catalog", response_model=CatalogEntryDetail, status_code=201)
async def admin_catalog_create(payload: CatalogEntryCreateInput):
    from ...main import IndexSession, StateSession

    service = _catalog_service()
    async with StateSession() as state, IndexSession() as index:
        try:
            result = await service.create_catalog_entry(
                state,
                content_type=payload.content_type,
                slug=payload.slug or _slugify(payload.title),
                title=payload.title,
                summary=payload.summary,
                description=payload.description,
                actor="admin",
            )
        except service.CatalogError as exc:
            raise _translate_catalog_error(exc) from exc
        await state.commit()
        return await _build_entry_detail(state, index, result.entry, published_only=False)


@router.put("/api/admin/catalog/{entry_id}", response_model=CatalogEntryDetail)
async def admin_catalog_update(entry_id: str, payload: CatalogEntryUpdateInput):
    from ...main import IndexSession, StateSession

    service = _catalog_service()
    async with StateSession() as state, IndexSession() as index:
        values = payload.model_dump(exclude_none=True, exclude={"expected_revision"})
        try:
            entry = await service.update_catalog_entry(
                state,
                entry_id,
                expected_revision=payload.expected_revision,
                actor="admin",
                **values,
            )
        except service.CatalogError as exc:
            raise _translate_catalog_error(exc) from exc
        await state.commit()
        return await _build_entry_detail(state, index, entry, published_only=False)


@router.post(
    "/api/admin/catalog/{entry_id}/locations",
    response_model=CatalogLocationSummary,
    status_code=201,
)
async def admin_catalog_bind_location(entry_id: str, payload: CatalogLocationBindInput):
    from ...main import IndexSession, StateSession

    service = _catalog_service()
    async with StateSession() as state, IndexSession() as index:
        try:
            entry = await service.get_catalog_entry(state, entry_id)
            asset = await state.get(CatalogAsset, payload.asset_id)
            if asset is None:
                raise service.CatalogAssetNotFound(payload.asset_id)
            release = await state.get(CatalogRelease, asset.release_id)
            if release is None or release.entry_id != entry.entry_id:
                raise service.CatalogAssetNotFound(payload.asset_id)
            result = await service.attach_catalog_location(
                state,
                index,
                asset_id=payload.asset_id,
                resource_id=payload.resource_id,
                label=payload.label,
                is_primary=payload.is_primary,
                actor="admin",
            )
        except service.CatalogError as exc:
            raise _translate_catalog_error(exc) from exc
        await state.commit()
        resource = await index.get(Resource, result.location.resource_id)
        return _location_to_summary(
            result.location, asset, resource, result.resolution.available
        )


@router.post("/api/admin/catalog/{entry_id}/preview", response_model=CatalogPreviewOutput)
async def admin_catalog_preview(entry_id: str):
    from ...main import IndexSession, StateSession

    service = _catalog_service()
    async with StateSession() as state, IndexSession() as index:
        try:
            preview = await service.validate_catalog_entry_for_preview(state, index, entry_id)
            entry = await service.get_catalog_entry(state, entry_id)
        except service.CatalogError as exc:
            raise _translate_catalog_error(exc) from exc
        reason = "; ".join(
            f"{row['location_id']}: {row['reason']}" for row in preview.unavailable_locations
        )
        return CatalogPreviewOutput(
            entry=await _build_entry_detail(state, index, entry, published_only=False),
            previewable=not preview.unavailable_locations and bool(preview.releases),
            reason=reason,
        )


@router.post("/api/admin/catalog/{entry_id}/publish", response_model=CatalogEntryDetail)
async def admin_catalog_publish(entry_id: str, payload: CatalogEntryPublishInput):
    from ...main import IndexSession, StateSession

    service = _catalog_service()
    async with StateSession() as state, IndexSession() as index:
        try:
            result = await service.publish_catalog_entry(
                state,
                index,
                entry_id,
                expected_revision=payload.expected_revision,
                actor="admin",
            )
        except service.CatalogError as exc:
            raise _translate_catalog_error(exc) from exc
        await state.commit()
        return await _build_entry_detail(state, index, result.entry, published_only=False)
