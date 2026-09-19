"""admin/alist 路由：AList 连接配置。"""

from fastapi import APIRouter, HTTPException, Query

from ...modules.providers.contracts.public import (
    ProviderAdminError,
    admin_connection_settings,
    browse_admin_directories,
    save_admin_connection,
    test_admin_connection,
)
from ...schemas import AListInput

router = APIRouter()


def _provider_http_exception(exc: ProviderAdminError) -> HTTPException:
    detail = (
        {"code": exc.code, "message": str(exc)}
        if exc.code
        else str(exc)
    )
    return HTTPException(exc.status_code, detail)


@router.get("/api/admin/alist")
async def get_alist():
    from ...main import StateSession

    async with StateSession() as state:
        return await admin_connection_settings(state)


@router.post("/api/admin/alist/test")
async def test_alist(payload: AListInput):
    from ...main import StateSession

    async with StateSession() as state:
        try:
            return await test_admin_connection(
                state,
                base_url=payload.base_url,
                username=payload.username,
                password=payload.password,
            )
        except ProviderAdminError as exc:
            raise _provider_http_exception(exc) from exc


@router.put("/api/admin/alist")
async def save_alist(payload: AListInput):
    from ...main import StateSession

    async with StateSession() as state:
        try:
            return await save_admin_connection(
                state,
                base_url=payload.base_url,
                username=payload.username,
                password=payload.password,
                remember_credentials=payload.remember_credentials,
            )
        except ProviderAdminError as exc:
            raise _provider_http_exception(exc) from exc


@router.get("/api/admin/alist/directories")
async def browse_alist_directories(
    path: str = Query("/", min_length=1, max_length=1000),
):
    from ...main import StateSession

    async with StateSession() as state:
        try:
            return await browse_admin_directories(state, path=path)
        except ProviderAdminError as exc:
            raise _provider_http_exception(exc) from exc
