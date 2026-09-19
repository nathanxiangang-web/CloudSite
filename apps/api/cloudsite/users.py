"""Administrator user HTTP edge."""

from fastapi import APIRouter, HTTPException, Query, Request

from .auth import validate_request_origin
from .database import StateSession
from .modules.users.contracts.public import (
    UserAdminError,
    create_admin_user,
    delete_admin_user,
    get_admin_user,
    list_admin_users,
    rename_admin_user,
    reset_admin_user_password,
    set_admin_user_status,
)
from .schemas import (
    AdminPasswordResetInput,
    AdminUserCreateInput,
    AdminUserUpdateInput,
    UserStatusInput,
)


router = APIRouter(
    prefix="/api/admin/users",
    tags=["admin-users"],
)


def _translate_user_error(
    exc: UserAdminError,
) -> HTTPException:
    detail = (
        {
            "code": exc.code,
            "message": exc.message,
        }
        if exc.code
        else exc.message
    )
    return HTTPException(
        exc.status_code,
        detail,
    )


def _password_confirm_error() -> HTTPException:
    return HTTPException(
        400,
        {
            "code": "PASSWORD_CONFIRM_MISMATCH",
            "message": "两次输入的密码不一致",
        },
    )


@router.get("")
async def list_users(
    search: str = Query(default="", max_length=100),
    status: str = Query(
        default="all",
        pattern=r"^(all|active|disabled|deleted)$",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    async with StateSession() as session:
        return await list_admin_users(
            session,
            search=search,
            status=status,
            page=page,
            page_size=page_size,
        )


@router.get("/{user_id}")
async def get_user(user_id: int):
    async with StateSession() as session:
        try:
            return await get_admin_user(
                session,
                user_id=user_id,
            )
        except UserAdminError as exc:
            raise _translate_user_error(exc) from exc


@router.post("", status_code=201)
async def create_user(
    payload: AdminUserCreateInput,
    request: Request,
):
    validate_request_origin(request)
    if payload.password != payload.password_confirm:
        raise _password_confirm_error()

    async with StateSession() as session:
        try:
            return await create_admin_user(
                session,
                username=payload.username,
                password=payload.password,
            )
        except UserAdminError as exc:
            raise _translate_user_error(exc) from exc


@router.patch("/{user_id}")
async def update_user(
    user_id: int,
    payload: AdminUserUpdateInput,
    request: Request,
):
    validate_request_origin(request)
    async with StateSession() as session:
        try:
            return await rename_admin_user(
                session,
                user_id=user_id,
                username=payload.username,
            )
        except UserAdminError as exc:
            raise _translate_user_error(exc) from exc


@router.patch("/{user_id}/status")
async def update_user_status(
    user_id: int,
    payload: UserStatusInput,
    request: Request,
):
    validate_request_origin(request)
    async with StateSession() as session:
        try:
            return await set_admin_user_status(
                session,
                user_id=user_id,
                status=payload.status,
            )
        except UserAdminError as exc:
            raise _translate_user_error(exc) from exc


@router.post("/{user_id}/reset-password")
async def reset_user_password(
    user_id: int,
    payload: AdminPasswordResetInput,
    request: Request,
):
    validate_request_origin(request)
    if (
        payload.new_password
        != payload.new_password_confirm
    ):
        raise _password_confirm_error()

    async with StateSession() as session:
        try:
            await reset_admin_user_password(
                session,
                user_id=user_id,
                new_password=payload.new_password,
            )
        except UserAdminError as exc:
            raise _translate_user_error(exc) from exc
    return {"ok": True}


@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    request: Request,
):
    validate_request_origin(request)
    async with StateSession() as session:
        try:
            await delete_admin_user(
                session,
                user_id=user_id,
            )
        except UserAdminError as exc:
            raise _translate_user_error(exc) from exc
    return {"ok": True}
