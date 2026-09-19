import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response
from pwdlib import PasswordHash
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .database import StateSession
from .modules.site.contracts.public import registration_enabled
from .modules.users.contracts.public import (
    UserAuthWorkflowError,
    authenticate_user_account,
    change_user_password,
    register_user_account,
)
from .platform.observability import write_operation_log
from .request_context import request_host, request_scheme
from .schemas import (
    UserLoginInput,
    UserPasswordChangeInput,
    UserRegisterInput,
)
from .sessions import (
    AuthenticatedUserView,
    SessionValidationError,
    USER_SESSION_COOKIE,
    clear_user_session_cookie,
    create_user_session,
    revoke_session,
    set_user_session_cookie,
    validate_user_session,
)


router = APIRouter(prefix="/api/auth", tags=["public-auth"])

# Compatibility helpers still consumed by the legacy admin users router.
password_hash = PasswordHash.recommended()
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{2,16}$")


def auth_error(
    status_code: int,
    code: str,
    message: str,
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def validate_username(username: str) -> tuple[str, str]:
    if (
        username != username.strip()
        or not USERNAME_PATTERN.fullmatch(username)
    ):
        raise auth_error(
            400,
            "USERNAME_INVALID",
            "用户名须为 2～16 位，仅允许字母、数字、下划线和短横线",
        )
    return username, username.lower()


def validate_password(
    value: str,
    *,
    field_name: str = "密码",
) -> str:
    if len(value) < 8 or len(value) > 72:
        raise auth_error(
            400,
            "PASSWORD_INVALID",
            f"{field_name}长度须为 8～72 位",
        )
    return value


def verify_password(value: str, encoded: str) -> bool:
    try:
        return password_hash.verify(value, encoded)
    except Exception:
        return False


def user_dict(user) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "status": (
            "deleted"
            if user.deleted_at is not None
            else user.status
        ),
        "created_at": user.created_at,
        "last_login_at": user.last_login_at,
        "password_changed_at": user.password_changed_at,
        "disabled_at": user.disabled_at,
        "deleted_at": user.deleted_at,
        "created_by_admin": user.created_by_admin,
    }


def _origin(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}".lower()


def validate_request_origin(request: Request) -> None:
    supplied = (
        request.headers.get("origin")
        or request.headers.get("referer")
    )
    if not supplied:
        return
    supplied_origin = _origin(supplied)
    scheme = request_scheme(request)
    host = request_host(request)
    allowed = {_origin(value) for value in settings.cors_origin_list}
    if host:
        allowed.add(_origin(f"{scheme}://{host}"))
    if not supplied_origin or supplied_origin not in allowed:
        raise auth_error(
            403,
            "CSRF_ORIGIN_INVALID",
            "请求来源校验失败",
        )


def _translate_user_auth_error(
    exc: UserAuthWorkflowError,
) -> HTTPException:
    return auth_error(
        exc.status_code,
        exc.code,
        exc.message,
    )


async def require_user(
    session: AsyncSession,
    request: Request,
) -> tuple[object, AuthenticatedUserView]:
    try:
        return await validate_user_session(
            session,
            request.cookies.get(USER_SESSION_COOKIE),
        )
    except SessionValidationError as exc:
        raise auth_error(
            exc.status_code,
            exc.code,
            exc.message,
        ) from exc


@router.post("/register", status_code=201)
async def register(
    payload: UserRegisterInput,
    request: Request,
    response: Response,
):
    validate_request_origin(request)
    username, normalized = validate_username(payload.username)
    password = validate_password(payload.password)
    if password != payload.password_confirm:
        raise auth_error(
            400,
            "PASSWORD_CONFIRM_MISMATCH",
            "两次输入的密码不一致",
        )

    now = datetime.now(timezone.utc)
    async with StateSession() as session:
        if not await registration_enabled(session):
            raise auth_error(
                403,
                "REGISTRATION_DISABLED",
                "当前站点未开放自助注册",
            )
        try:
            user = await register_user_account(
                session,
                username=username,
                username_normalized=normalized,
                password=password,
                now=now,
            )
        except UserAuthWorkflowError as exc:
            raise _translate_user_auth_error(exc) from exc

        _, token = await create_user_session(
            session,
            user.id,
            now,
            request,
        )
        await session.commit()

    set_user_session_cookie(request, response, token)
    return user_dict(user)


@router.post("/login")
async def login(
    payload: UserLoginInput,
    request: Request,
    response: Response,
):
    validate_request_origin(request)
    try:
        _, normalized = validate_username(payload.username)
    except HTTPException:
        normalized = ""

    now = datetime.now(timezone.utc)
    async with StateSession() as session:
        try:
            user = await authenticate_user_account(
                session,
                username_normalized=normalized,
                password=payload.password,
                now=now,
            )
        except UserAuthWorkflowError as exc:
            raise _translate_user_auth_error(exc) from exc

        _, token = await create_user_session(
            session,
            user.id,
            now,
            request,
        )
        await session.commit()

    set_user_session_cookie(request, response, token)
    return user_dict(user)


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
):
    validate_request_origin(request)
    async with StateSession() as session:
        await revoke_session(
            session,
            request.cookies.get(USER_SESSION_COOKIE),
        )
        await write_operation_log(
            session,
            module="auth",
            action="user_logout",
            message="前台用户退出登录",
        )
        await session.commit()

    clear_user_session_cookie(response)
    return {"ok": True}


@router.get("/me")
async def me(request: Request):
    async with StateSession() as session:
        _, user = await require_user(session, request)
        await session.commit()
        return {
            "authenticated": True,
            "user": user_dict(user),
        }


@router.post("/change-password")
async def change_password(
    payload: UserPasswordChangeInput,
    request: Request,
    response: Response,
):
    validate_request_origin(request)
    new_password = validate_password(
        payload.new_password,
        field_name="新密码",
    )
    if new_password != payload.new_password_confirm:
        raise auth_error(
            400,
            "PASSWORD_CONFIRM_MISMATCH",
            "两次输入的新密码不一致",
        )

    now = datetime.now(timezone.utc)
    async with StateSession() as session:
        _, authenticated = await require_user(session, request)
        try:
            user = await change_user_password(
                session,
                user_id=authenticated.id,
                current_password=payload.current_password,
                new_password=new_password,
                now=now,
            )
        except UserAuthWorkflowError as exc:
            raise _translate_user_auth_error(exc) from exc

        _, token = await create_user_session(
            session,
            user.id,
            now,
            request,
        )
        await session.commit()

    set_user_session_cookie(request, response, token)
    return {"ok": True}
