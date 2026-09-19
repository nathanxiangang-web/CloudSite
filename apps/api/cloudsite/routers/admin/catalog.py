"""Administrator Catalog routes backed by the real application service."""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Query
from ...catalog_schemas import (
    CatalogAssetCreateInput,
    CatalogAssetUpdateInput,
    CatalogEntryCreateInput,
    CatalogEntryDetail,
    CatalogEntryListOutput,
    CatalogEntryPublishInput,
    CatalogEntrySummary,
    CatalogEntryUpdateInput,
    CatalogLocationAttachInput,
    CatalogLocationBindInput,
    CatalogLocationSummary,
    CatalogLocationUpdateInput,
    CatalogPreviewOutput,
    CatalogReleaseCreateInput,
    CatalogReleaseUpdateInput,
)
from ...modules.catalog.contracts import public as catalog_api

router = APIRouter()


def _catalog_service():
    return catalog_api


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
    if isinstance(exc, service.CatalogDeleteConflict):
        return HTTPException(
            409,
            {
                "code": "CATALOG_DELETE_CONFLICT",
                "message": exc.reason,
            },
        )
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


@router.get("/api/admin/catalog", response_model=CatalogEntryListOutput)
async def admin_catalog_list(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    from ...main import StateSession

    async with StateSession() as state:
        payload = await catalog_api.admin_entry_summary_page(
            state,
            page=page,
            page_size=page_size,
        )
        return CatalogEntryListOutput(**payload)


@router.get("/api/admin/catalog/entries")
async def admin_catalog_entries(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=100),
):
    from ...main import IndexSession, StateSession

    async with StateSession() as state, IndexSession() as index:
        return await catalog_api.admin_entry_view_page(
            state,
            index,
            page=page,
            page_size=page_size,
        )


@router.post("/api/admin/catalog/entries", status_code=201)
async def admin_catalog_create_entry(payload: CatalogEntryCreateInput):
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
        return await catalog_api.admin_entry_view(state, index, result.entry.entry_id)


@router.get("/api/admin/catalog/entries/{entry_id}")
async def admin_catalog_entry(entry_id: str):
    from ...main import IndexSession, StateSession

    async with StateSession() as state, IndexSession() as index:
        try:
            return await catalog_api.admin_entry_view(
                state,
                index,
                entry_id,
            )
        except catalog_api.CatalogError as exc:
            raise _translate_catalog_error(exc) from exc


@router.patch("/api/admin/catalog/entries/{entry_id}")
async def admin_catalog_patch_entry(entry_id: str, payload: CatalogEntryUpdateInput):
    from ...main import IndexSession, StateSession

    service = _catalog_service()
    values = payload.model_dump(exclude_unset=True, exclude={"expected_revision"})
    if values.get("status") == "published":
        raise HTTPException(
            400,
            {"code": "CATALOG_PUBLISH_ACTION_REQUIRED", "message": "Use the publish action"},
        )
    async with StateSession() as state, IndexSession() as index:
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
        return await catalog_api.admin_entry_view(state, index, entry.entry_id)


@router.post("/api/admin/catalog/entries/{entry_id}/publish")
async def admin_catalog_publish_entry(entry_id: str, payload: CatalogEntryPublishInput):
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
        return await catalog_api.admin_entry_view(state, index, result.entry.entry_id)


@router.get("/api/admin/catalog/{entry_id}", response_model=CatalogEntryDetail)
async def admin_catalog_detail(entry_id: str):
    from ...main import IndexSession, StateSession

    async with StateSession() as state, IndexSession() as index:
        try:
            return await catalog_api.admin_legacy_entry_detail(
                state,
                index,
                entry_id,
                published_only=False,
            )
        except catalog_api.CatalogError as exc:
            raise _translate_catalog_error(exc) from exc


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
        return await catalog_api.admin_legacy_entry_detail(
            state,
            index,
            result.entry.entry_id,
            published_only=False,
        )


@router.put("/api/admin/catalog/{entry_id}", response_model=CatalogEntryDetail)
async def admin_catalog_update(entry_id: str, payload: CatalogEntryUpdateInput):
    from ...main import IndexSession, StateSession

    service = _catalog_service()
    async with StateSession() as state, IndexSession() as index:
        values = payload.model_dump(exclude_unset=True, exclude={"expected_revision"})
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
        return await catalog_api.admin_legacy_entry_detail(
            state,
            index,
            entry.entry_id,
            published_only=False,
        )


@router.post(
    "/api/admin/catalog/{entry_id}/locations",
    response_model=CatalogLocationSummary,
    status_code=201,
)
async def admin_catalog_bind_location(
    entry_id: str,
    payload: CatalogLocationBindInput,
):
    from ...main import IndexSession, StateSession

    async with StateSession() as state, IndexSession() as index:
        try:
            result = await catalog_api.admin_attach_entry_location(
                state,
                index,
                entry_id=entry_id,
                asset_id=payload.asset_id,
                resource_id=payload.resource_id,
                label=payload.label,
                is_primary=payload.is_primary,
                actor="admin",
            )
        except catalog_api.CatalogError as exc:
            raise _translate_catalog_error(exc) from exc
        await state.commit()
        return CatalogLocationSummary(**result)


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
            entry=await catalog_api.admin_legacy_entry_detail(
                state,
                index,
                entry.entry_id,
                published_only=False,
            ),
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
        return await catalog_api.admin_legacy_entry_detail(
            state,
            index,
            result.entry.entry_id,
            published_only=False,
        )


# ---- C2 Release CRUD ----

@router.get("/api/admin/catalog/entries/{entry_id}/releases")
async def admin_catalog_releases_list(entry_id: str):
    from ...main import IndexSession, StateSession

    async with StateSession() as state, IndexSession() as index:
        try:
            items = await catalog_api.admin_release_views(
                state,
                index,
                entry_id,
            )
        except catalog_api.CatalogError as exc:
            raise _translate_catalog_error(exc) from exc
        return {"items": items}


@router.post("/api/admin/catalog/entries/{entry_id}/releases", status_code=201)
async def admin_catalog_release_create(entry_id: str, payload: CatalogReleaseCreateInput):
    from ...main import IndexSession, StateSession

    service = _catalog_service()
    async with StateSession() as state, IndexSession() as index:
        try:
            result = await service.create_catalog_release(
                state,
                entry_id=entry_id,
                slug=payload.slug,
                title=payload.title,
                release_notes=payload.release_notes,
                channel=payload.channel,
                release_date=payload.release_date,
                is_recommended=payload.is_recommended,
                sort_order=payload.sort_order,
                actor="admin",
            )
        except service.CatalogError as exc:
            raise _translate_catalog_error(exc) from exc
        await state.commit()
        return await catalog_api.admin_release_view(
            state,
            index,
            result.release.release_id,
        )


@router.get("/api/admin/catalog/releases/{release_id}")
async def admin_catalog_release_detail(release_id: str):
    from ...main import IndexSession, StateSession

    async with StateSession() as state, IndexSession() as index:
        try:
            return await catalog_api.admin_release_view(
                state,
                index,
                release_id,
            )
        except catalog_api.CatalogError as exc:
            raise _translate_catalog_error(exc) from exc


@router.patch("/api/admin/catalog/releases/{release_id}")
async def admin_catalog_release_update(release_id: str, payload: CatalogReleaseUpdateInput):
    from ...main import IndexSession, StateSession

    service = _catalog_service()
    values = payload.model_dump(exclude_unset=True)
    async with StateSession() as state, IndexSession() as index:
        try:
            release = await service.update_catalog_release(
                state, release_id, actor="admin", **values
            )
        except service.CatalogError as exc:
            raise _translate_catalog_error(exc) from exc
        await state.commit()
        return await catalog_api.admin_release_view(
            state,
            index,
            release.release_id,
        )


@router.delete("/api/admin/catalog/releases/{release_id}", status_code=204)
async def admin_catalog_release_delete(release_id: str):
    from ...main import StateSession

    async with StateSession() as state:
        try:
            await catalog_api.delete_catalog_release(
                state,
                release_id,
                actor="admin",
            )
        except catalog_api.CatalogError as exc:
            raise _translate_catalog_error(exc) from exc
        await state.commit()


# ---- C2 Asset CRUD ----

@router.get("/api/admin/catalog/releases/{release_id}/assets")
async def admin_catalog_assets_list(release_id: str):
    from ...main import IndexSession, StateSession

    async with StateSession() as state, IndexSession() as index:
        try:
            items = await catalog_api.admin_asset_views(
                state,
                index,
                release_id,
            )
        except catalog_api.CatalogError as exc:
            raise _translate_catalog_error(exc) from exc
        return {"items": items}


@router.post("/api/admin/catalog/releases/{release_id}/assets", status_code=201)
async def admin_catalog_asset_create(release_id: str, payload: CatalogAssetCreateInput):
    from ...main import IndexSession, StateSession

    service = _catalog_service()
    async with StateSession() as state, IndexSession() as index:
        try:
            result = await service.create_catalog_asset(
                state,
                release_id=release_id,
                slug=payload.slug,
                display_name=payload.display_name,
                platform=payload.platform,
                kind=payload.kind,
                architecture=payload.architecture,
                package_type=payload.package_type,
                language=payload.language,
                build_label=payload.build_label,
                checksum=payload.checksum,
                checksum_algorithm=payload.checksum_algorithm,
                size=payload.size,
                sort_order=payload.sort_order,
                actor="admin",
            )
        except service.CatalogError as exc:
            raise _translate_catalog_error(exc) from exc
        await state.commit()
        return await catalog_api.admin_asset_view(
            state,
            index,
            result.asset.asset_id,
        )


@router.get("/api/admin/catalog/assets/{asset_id}")
async def admin_catalog_asset_detail(asset_id: str):
    from ...main import IndexSession, StateSession

    async with StateSession() as state, IndexSession() as index:
        try:
            return await catalog_api.admin_asset_view(
                state,
                index,
                asset_id,
            )
        except catalog_api.CatalogError as exc:
            raise _translate_catalog_error(exc) from exc


@router.patch("/api/admin/catalog/assets/{asset_id}")
async def admin_catalog_asset_update(asset_id: str, payload: CatalogAssetUpdateInput):
    from ...main import IndexSession, StateSession

    service = _catalog_service()
    values = payload.model_dump(exclude_unset=True)
    async with StateSession() as state, IndexSession() as index:
        try:
            asset = await service.update_catalog_asset(state, asset_id, actor="admin", **values)
        except service.CatalogError as exc:
            raise _translate_catalog_error(exc) from exc
        await state.commit()
        return await catalog_api.admin_asset_view(
            state,
            index,
            asset.asset_id,
        )


@router.delete("/api/admin/catalog/assets/{asset_id}", status_code=204)
async def admin_catalog_asset_delete(asset_id: str):
    from ...main import StateSession

    async with StateSession() as state:
        try:
            await catalog_api.delete_catalog_asset(
                state,
                asset_id,
                actor="admin",
            )
        except catalog_api.CatalogError as exc:
            raise _translate_catalog_error(exc) from exc
        await state.commit()


# ---- C2 Location CRUD ----

@router.get("/api/admin/catalog/assets/{asset_id}/locations")
async def admin_catalog_locations_list(asset_id: str):
    from ...main import IndexSession, StateSession

    async with StateSession() as state, IndexSession() as index:
        try:
            items = await catalog_api.admin_location_views(
                state,
                index,
                asset_id,
            )
        except catalog_api.CatalogError as exc:
            raise _translate_catalog_error(exc) from exc
        return {"items": items}


@router.post("/api/admin/catalog/assets/{asset_id}/locations", status_code=201)
async def admin_catalog_location_attach(asset_id: str, payload: CatalogLocationAttachInput):
    from ...main import IndexSession, StateSession

    service = _catalog_service()
    async with StateSession() as state, IndexSession() as index:
        try:
            result = await service.attach_catalog_location(
                state,
                index,
                asset_id=asset_id,
                resource_id=payload.resource_id,
                label=payload.label,
                is_primary=payload.is_primary,
                actor="admin",
            )
        except service.CatalogError as exc:
            raise _translate_catalog_error(exc) from exc
        await state.commit()
        return await catalog_api.admin_location_view_for_asset(
            state,
            index,
            asset_id=asset_id,
            location=result.location,
        )


@router.patch("/api/admin/catalog/locations/{location_id}")
async def admin_catalog_location_update(location_id: str, payload: CatalogLocationUpdateInput):
    from ...main import IndexSession, StateSession

    service = _catalog_service()
    values = payload.model_dump(exclude_unset=True)
    async with StateSession() as state, IndexSession() as index:
        try:
            location = await service.update_catalog_location(state, location_id, actor="admin", **values)
        except service.CatalogError as exc:
            raise _translate_catalog_error(exc) from exc
        await state.commit()
        return await catalog_api.admin_location_view_for_asset(
            state,
            index,
            asset_id=location.asset_id,
            location=location,
        )


@router.delete("/api/admin/catalog/locations/{location_id}", status_code=204)
async def admin_catalog_location_detach(location_id: str):
    from ...main import StateSession

    service = _catalog_service()
    async with StateSession() as state:
        try:
            await service.delete_catalog_location(state, location_id, actor="admin")
        except service.CatalogError as exc:
            raise _translate_catalog_error(exc) from exc
        await state.commit()
