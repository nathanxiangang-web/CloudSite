"""Authenticated-user reads for published Catalog entries."""
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from ..catalog_schemas import CatalogEntryDetail, CatalogEntryListOutput
from ..models import CatalogEntry
from .admin.catalog import _build_entry_detail, _entry_to_summary

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
