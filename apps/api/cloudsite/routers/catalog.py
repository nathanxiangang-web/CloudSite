"""catalog router: published Catalog reading for authenticated users.

Routes are mounted under /api/catalog. The existing admin_session_middleware
requires a valid user session for any /api/** path outside the public allowlist,
so these endpoints are reachable only by authenticated users (public means
product-published inside the current login contract, not anonymous). Only
published entries are exposed; unpublished entries return 404 and unavailable
locations are stripped by the service when published_only=True.

Path identifiers use the reviewed C1 stable-ID contract (str, 35 characters)
matching CatalogEntry.entry_id.
"""
from fastapi import APIRouter, HTTPException, Query

from ..catalog_schemas import (
    CatalogEntryDetail,
    CatalogEntryListOutput,
    CatalogEntryNotFound,
    CatalogError,
    CatalogRevisionConflict,
)

router = APIRouter()


def _catalog_service():
    """Lazily import the parallel-developed catalog service module.

    Deferring the import to request time keeps application startup independent
    of services/catalog.py availability; the import/runtime check is recorded
    as deferred in RESULT.md.
    """
    from ..services import catalog  # noqa: PLC0415

    return catalog


def _translate_catalog_error(exc: CatalogError) -> HTTPException:
    if isinstance(exc, CatalogEntryNotFound):
        return HTTPException(404, "Catalog entry not found")
    if isinstance(exc, CatalogRevisionConflict):
        return HTTPException(409, "Catalog revision conflict")
    return HTTPException(500, "Catalog service error")


@router.get("/api/catalog", response_model=CatalogEntryListOutput)
async def public_catalog_list(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    from ..main import IndexSession, StateSession

    service = _catalog_service()
    async with StateSession() as state, IndexSession() as index:
        return await service.list_catalog_entries(
            state, index, published_only=True, page=page, page_size=page_size
        )


@router.get("/api/catalog/{entry_id}", response_model=CatalogEntryDetail)
async def public_catalog_detail(entry_id: str):
    from ..main import IndexSession, StateSession

    service = _catalog_service()
    async with StateSession() as state, IndexSession() as index:
        try:
            entry = await service.get_catalog_entry(state, index, entry_id, published_only=True)
        except CatalogError as exc:
            raise _translate_catalog_error(exc) from exc
        if entry is None:
            raise HTTPException(404, "Catalog entry not found")
        return entry
