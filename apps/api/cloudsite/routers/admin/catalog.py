"""admin/catalog router: Catalog entry authoring for administrators.

Routes are mounted under /api/admin/catalog and protected by the existing
admin_session_middleware (any /api/admin/** path requires an administrator
cookie). HTTP translation lives here; business validation lives in
services/catalog.py, imported lazily so application startup does not depend on
the parallel-developed service module being present.

Path and body identifiers use the reviewed C1 stable-ID contract (str, 35
characters) matching CatalogEntry.entry_id and CatalogAsset.asset_id.
"""
from fastapi import APIRouter, HTTPException, Query

from ...catalog_schemas import (
    CatalogEntryCreateInput,
    CatalogEntryDetail,
    CatalogEntryListOutput,
    CatalogEntryNotFound,
    CatalogEntryNotPreviewable,
    CatalogEntryUpdateInput,
    CatalogError,
    CatalogLocationBindInput,
    CatalogLocationSummary,
    CatalogLocationUnavailable,
    CatalogPreviewOutput,
    CatalogRevisionConflict,
)

router = APIRouter()


def _catalog_service():
    """Lazily import the parallel-developed catalog service module.

    Deferring the import to request time keeps application startup independent
    of services/catalog.py availability; the import/runtime check is recorded
    as deferred in RESULT.md.
    """
    from ...services import catalog  # noqa: PLC0415

    return catalog


def _translate_catalog_error(exc: CatalogError) -> HTTPException:
    if isinstance(exc, CatalogEntryNotFound):
        return HTTPException(404, "Catalog entry not found")
    if isinstance(exc, CatalogRevisionConflict):
        return HTTPException(409, "Catalog revision conflict")
    if isinstance(exc, CatalogLocationUnavailable):
        return HTTPException(409, "Catalog location unavailable")
    if isinstance(exc, CatalogEntryNotPreviewable):
        return HTTPException(409, "Catalog entry not previewable")
    return HTTPException(500, "Catalog service error")


@router.get("/api/admin/catalog", response_model=CatalogEntryListOutput)
async def admin_catalog_list(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    from ...main import IndexSession, StateSession

    service = _catalog_service()
    async with StateSession() as state, IndexSession() as index:
        return await service.list_catalog_entries(
            state, index, published_only=False, page=page, page_size=page_size
        )


@router.get("/api/admin/catalog/{entry_id}", response_model=CatalogEntryDetail)
async def admin_catalog_detail(entry_id: str):
    from ...main import IndexSession, StateSession

    service = _catalog_service()
    async with StateSession() as state, IndexSession() as index:
        entry = await service.get_catalog_entry(state, index, entry_id)
        if entry is None:
            raise HTTPException(404, "Catalog entry not found")
        return entry


@router.post("/api/admin/catalog", response_model=CatalogEntryDetail, status_code=201)
async def admin_catalog_create(payload: CatalogEntryCreateInput):
    from ...main import IndexSession, StateSession

    service = _catalog_service()
    async with StateSession() as state, IndexSession() as index:
        try:
            entry = await service.create_catalog_entry(state, index, payload)
        except CatalogError as exc:
            raise _translate_catalog_error(exc) from exc
        await state.commit()
        return entry


@router.put("/api/admin/catalog/{entry_id}", response_model=CatalogEntryDetail)
async def admin_catalog_update(entry_id: str, payload: CatalogEntryUpdateInput):
    from ...main import IndexSession, StateSession

    service = _catalog_service()
    async with StateSession() as state, IndexSession() as index:
        try:
            entry = await service.update_catalog_entry(state, index, entry_id, payload)
        except CatalogError as exc:
            raise _translate_catalog_error(exc) from exc
        await state.commit()
        return entry


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
            location = await service.attach_catalog_location(state, index, entry_id, payload)
        except CatalogError as exc:
            raise _translate_catalog_error(exc) from exc
        await state.commit()
        return location


@router.post(
    "/api/admin/catalog/{entry_id}/preview",
    response_model=CatalogPreviewOutput,
)
async def admin_catalog_preview(entry_id: str):
    from ...main import IndexSession, StateSession

    service = _catalog_service()
    async with StateSession() as state, IndexSession() as index:
        try:
            return await service.validate_catalog_entry_for_preview(state, index, entry_id)
        except CatalogError as exc:
            raise _translate_catalog_error(exc) from exc


@router.post(
    "/api/admin/catalog/{entry_id}/publish",
    response_model=CatalogEntryDetail,
)
async def admin_catalog_publish(entry_id: str):
    from ...main import IndexSession, StateSession

    service = _catalog_service()
    async with StateSession() as state, IndexSession() as index:
        try:
            entry = await service.publish_catalog_entry(state, index, entry_id)
        except CatalogError as exc:
            raise _translate_catalog_error(exc) from exc
        await state.commit()
        return entry
