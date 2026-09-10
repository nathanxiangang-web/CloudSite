"""Administrator Catalog routes backed by the real application service."""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

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
from ...models import CatalogAsset, CatalogEntry, CatalogLocation, CatalogRelease, Resource
from ...services.catalog_views import catalog_asset_view, catalog_entry_view, catalog_release_view

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


@router.get("/api/admin/catalog/entries")
async def admin_catalog_entries(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=100),
):
    from ...main import IndexSession, StateSession

    service = _catalog_service()
    async with StateSession() as state, IndexSession() as index:
        entries = await service.list_catalog_entries(
            state, limit=page_size, offset=(page - 1) * page_size
        )
        items = [
            await catalog_entry_view(state, index, entry, public=False)
            for entry in entries
        ]
        total = int(await state.scalar(select(func.count()).select_from(CatalogEntry)) or 0)
        return {
            "items": items,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": _total_pages(total, page_size),
        }


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
        return await catalog_entry_view(state, index, result.entry, public=False)


@router.get("/api/admin/catalog/entries/{entry_id}")
async def admin_catalog_entry(entry_id: str):
    from ...main import IndexSession, StateSession

    service = _catalog_service()
    async with StateSession() as state, IndexSession() as index:
        try:
            entry = await service.get_catalog_entry(state, entry_id)
        except service.CatalogError as exc:
            raise _translate_catalog_error(exc) from exc
        return await catalog_entry_view(state, index, entry, public=False)


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
        return await catalog_entry_view(state, index, entry, public=False)


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
        return await catalog_entry_view(state, index, result.entry, public=False)


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


# ---- C2 Release CRUD ----

@router.get("/api/admin/catalog/entries/{entry_id}/releases")
async def admin_catalog_releases_list(entry_id: str):
    from ...main import IndexSession, StateSession

    service = _catalog_service()
    async with StateSession() as state, IndexSession() as index:
        try:
            await service.get_catalog_entry(state, entry_id)
            releases = await service.list_catalog_releases(state, entry_id)
        except service.CatalogError as exc:
            raise _translate_catalog_error(exc) from exc
        return {
            "items": [
                await catalog_release_view(state, index, release, public=False)
                for release in releases
            ]
        }


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
        return await catalog_release_view(state, index, result.release, public=False)


@router.get("/api/admin/catalog/releases/{release_id}")
async def admin_catalog_release_detail(release_id: str):
    from ...main import IndexSession, StateSession

    service = _catalog_service()
    async with StateSession() as state, IndexSession() as index:
        try:
            release = await service.get_catalog_release(state, release_id)
        except service.CatalogError as exc:
            raise _translate_catalog_error(exc) from exc
        return await catalog_release_view(state, index, release, public=False)


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
        return await catalog_release_view(state, index, release, public=False)


@router.delete("/api/admin/catalog/releases/{release_id}", status_code=204)
async def admin_catalog_release_delete(release_id: str):
    from ...main import StateSession
    from ...services.catalog_metadata import append_catalog_revision

    service = _catalog_service()
    async with StateSession() as state:
        try:
            release = await service.get_catalog_release(state, release_id)
            assets = await service.list_catalog_assets(state, release_id)
        except service.CatalogError as exc:
            raise _translate_catalog_error(exc) from exc
        if assets:
            raise HTTPException(
                409,
                {"code": "CATALOG_DELETE_CONFLICT", "message": "release still has assets; remove them first"},
            )
        before = {"entry_id": release.entry_id, "slug": release.slug, "title": release.title, "status": release.status}
        await state.delete(release)
        await append_catalog_revision(
            state, target_type="release", target_id=release_id, action="delete", actor="admin", before=before
        )
        await state.commit()


# ---- C2 Asset CRUD ----

async def _asset_content_type(state, asset: CatalogAsset) -> str:
    release = await state.get(CatalogRelease, asset.release_id)
    if release is None:
        return "file"
    entry = await state.get(CatalogEntry, release.entry_id)
    return entry.content_type if entry is not None else "file"


@router.get("/api/admin/catalog/releases/{release_id}/assets")
async def admin_catalog_assets_list(release_id: str):
    from ...main import IndexSession, StateSession

    service = _catalog_service()
    async with StateSession() as state, IndexSession() as index:
        try:
            release = await service.get_catalog_release(state, release_id)
            assets = await service.list_catalog_assets(state, release_id)
        except service.CatalogError as exc:
            raise _translate_catalog_error(exc) from exc
        entry = await state.get(CatalogEntry, release.entry_id)
        content_type = entry.content_type if entry is not None else "file"
        return {
            "items": [
                await catalog_asset_view(state, index, asset, content_type=content_type, public=False)
                for asset in assets
            ]
        }


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
        content_type = await _asset_content_type(state, result.asset)
        return await catalog_asset_view(state, index, result.asset, content_type=content_type, public=False)


@router.get("/api/admin/catalog/assets/{asset_id}")
async def admin_catalog_asset_detail(asset_id: str):
    from ...main import IndexSession, StateSession

    service = _catalog_service()
    async with StateSession() as state, IndexSession() as index:
        try:
            asset = await service.get_catalog_asset(state, asset_id)
        except service.CatalogError as exc:
            raise _translate_catalog_error(exc) from exc
        content_type = await _asset_content_type(state, asset)
        return await catalog_asset_view(state, index, asset, content_type=content_type, public=False)


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
        content_type = await _asset_content_type(state, asset)
        return await catalog_asset_view(state, index, asset, content_type=content_type, public=False)


@router.delete("/api/admin/catalog/assets/{asset_id}", status_code=204)
async def admin_catalog_asset_delete(asset_id: str):
    from ...main import StateSession
    from ...services.catalog_metadata import append_catalog_revision

    service = _catalog_service()
    async with StateSession() as state:
        try:
            asset = await service.get_catalog_asset(state, asset_id)
        except service.CatalogError as exc:
            raise _translate_catalog_error(exc) from exc
        before = {"release_id": asset.release_id, "slug": asset.slug, "display_name": asset.display_name, "status": asset.status}
        await state.delete(asset)
        await append_catalog_revision(
            state, target_type="asset", target_id=asset_id, action="delete", actor="admin", before=before
        )
        await state.commit()


# ---- C2 Location CRUD ----

async def _location_view(state, index, location: CatalogLocation, content_type: str) -> dict:
    service = _catalog_service()
    roots = await service.enabled_root_ids(state)
    resource = await index.get(Resource, location.resource_id)
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
        "created_at": location.created_at,
        "updated_at": location.updated_at,
    }


@router.get("/api/admin/catalog/assets/{asset_id}/locations")
async def admin_catalog_locations_list(asset_id: str):
    from ...main import IndexSession, StateSession

    service = _catalog_service()
    async with StateSession() as state, IndexSession() as index:
        try:
            asset = await service.get_catalog_asset(state, asset_id)
            locations = await service.list_catalog_locations(state, asset_id)
        except service.CatalogError as exc:
            raise _translate_catalog_error(exc) from exc
        content_type = await _asset_content_type(state, asset)
        return {"items": [await _location_view(state, index, loc, content_type) for loc in locations]}


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
        asset = await service.get_catalog_asset(state, asset_id)
        content_type = await _asset_content_type(state, asset)
        return await _location_view(state, index, result.location, content_type)


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
        asset = await service.get_catalog_asset(state, location.asset_id)
        content_type = await _asset_content_type(state, asset)
        return await _location_view(state, index, location, content_type)


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
