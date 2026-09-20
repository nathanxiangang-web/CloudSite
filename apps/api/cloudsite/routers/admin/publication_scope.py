"""B2 Catalog publication-scope routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...auth import validate_request_origin
from ...modules.catalog.contracts.public import (
    CatalogPublicationNotFound,
    CatalogPublicationNotPublic,
    list_publication_scope_entries,
    public_catalog_entry,
    update_publication_scope,
)

router = APIRouter()


class PublicationScopeInput(BaseModel):
    publicly_visible: bool


@router.get("/api/admin/publication-scope")
async def list_publication_scope():
    from ...main import StateSession

    async with StateSession() as state:
        return {
            "items": await list_publication_scope_entries(state)
        }


@router.put(
    "/api/admin/catalog/entries/{entry_id}/publication-scope"
)
async def update_publication_scope_route(
    entry_id: str,
    payload: PublicationScopeInput,
    request: Request,
):
    from ...main import StateSession

    validate_request_origin(request)
    async with StateSession() as state:
        try:
            result = await update_publication_scope(
                state,
                entry_id=entry_id,
                publicly_visible=payload.publicly_visible,
            )
        except CatalogPublicationNotFound as exc:
            raise HTTPException(
                404,
                {
                    "code": "CATALOG_ENTRY_NOT_FOUND",
                    "message": "Catalog entry not found",
                },
            ) from exc

    if not payload.publicly_visible:
        from ..home import invalidate_home_cache

        invalidate_home_cache()
    return result


@router.get("/api/public/catalog/{entry_id}")
async def public_catalog_entry_dto(entry_id: str):
    from ...main import StateSession

    async with StateSession() as state:
        try:
            return await public_catalog_entry(
                state,
                entry_id=entry_id,
            )
        except CatalogPublicationNotPublic as exc:
            raise HTTPException(
                404,
                {
                    "code": "CATALOG_ENTRY_NOT_PUBLIC",
                    "message": "条目未公开",
                },
            ) from exc
