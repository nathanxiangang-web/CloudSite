"""admin/content_roots 路由：根目录映射管理。"""

from fastapi import APIRouter, HTTPException

from ...app.root_mapping_lifecycle import delete_root_mapping_with_identity_cleanup
from ...modules.providers.contracts.public import (
    ProviderAdminError,
    create_root_mapping,
    list_root_mappings,
    update_root_mapping,
    validate_root_mapping_path as validate_provider_root_mapping_path,
)
from ...schemas import RootMappingInput
from ..home import invalidate_home_cache

router = APIRouter()


def _provider_http_exception(exc: ProviderAdminError) -> HTTPException:
    detail = (
        {"code": exc.code, "message": str(exc)}
        if exc.code
        else str(exc)
    )
    return HTTPException(exc.status_code, detail)


async def validate_root_mapping_path(
    path: str,
    connection_id: int = 1,
) -> str:
    """Compatibility seam delegating path validation to Providers."""

    from ...main import StateSession

    async with StateSession() as state:
        try:
            return await validate_provider_root_mapping_path(
                state,
                path=path,
                connection_id=connection_id,
            )
        except ProviderAdminError as exc:
            raise _provider_http_exception(exc) from exc


@router.get("/api/admin/root-mappings")
async def get_root_mappings():
    from ...main import StateSession

    async with StateSession() as state:
        return {"items": await list_root_mappings(state)}


@router.post("/api/admin/root-mappings")
async def add_root_mapping(payload: RootMappingInput):
    from ...main import StateSession

    normalized_path = await validate_root_mapping_path(
        payload.alist_path,
        payload.connection_id,
    )
    async with StateSession() as state:
        try:
            mapping_id = await create_root_mapping(
                state,
                values=payload.model_dump(),
                validated_path=normalized_path,
            )
        except ProviderAdminError as exc:
            raise _provider_http_exception(exc) from exc
    invalidate_home_cache()
    return {"id": mapping_id}


@router.put("/api/admin/root-mappings/{mapping_id}")
async def update_root_mapping_route(
    mapping_id: int,
    payload: RootMappingInput,
):
    from ...main import StateSession

    normalized_path = await validate_root_mapping_path(
        payload.alist_path,
        payload.connection_id,
    )
    async with StateSession() as state:
        try:
            await update_root_mapping(
                state,
                mapping_id,
                values=payload.model_dump(),
                validated_path=normalized_path,
            )
        except ProviderAdminError as exc:
            raise _provider_http_exception(exc) from exc
    invalidate_home_cache()
    return {"ok": True}


@router.delete("/api/admin/root-mappings/{mapping_id}")
async def delete_root_mapping_route(mapping_id: int):
    from ...main import StateSession

    async with StateSession() as state:
        try:
            await delete_root_mapping_with_identity_cleanup(state, mapping_id)
        except ProviderAdminError as exc:
            raise _provider_http_exception(exc) from exc
    invalidate_home_cache()
    return {"ok": True}
