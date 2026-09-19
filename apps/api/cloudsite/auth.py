"""Public-auth HTTP edge and compatibility helpers."""

import re
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response
from pwdlib import PasswordHash

from .config import settings
from .database import StateSession
from .modules.site.contracts.public import registration_enabled
from .modules.users.contracts.public import (
    AuthenticatedUserView,
    UserAuthenticationError,
    change_user_password,
    login_user,
    logout_user,
    register_user,
)
from .request_context import request_host, request_scheme
from .schemas import (
    UserLoginInput,
    UserPasswordChangeInput,
    UserRegisterInput,
)
from .sessions import (
    USER_SESSION_COOKIE,
    SessionValidationError,
    clear_user_session_cookie,
    hash_request_metadata,
    set_user_session_cookie,
    validate_user_session,
)


router = APIRouter(prefix="/api/auth", tags=["public-auth"])

# Compatibility helpers still consumed by legacy admin user routes/tests.
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


def user_dict(user: Any) -> dict:
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
    allowed = {
        _origin(value)
        for value in settings.cors_origin_list
    }
    if host:
        allowed.add(_origin(f"{scheme}://{host}"))
    if not supplied_origin or supplied_origin not in allowed:
        raise auth_error(
            403,
            "CSRF_ORIGIN_INVALID",
            "请求来源校验失败",
        )


def _session_metadata(
    request: Request,
) -> tuple[str | None, str | None]:
    return (
        hash_request_metadata(
            request.client.host
            if request.client
            else ""
        ),
        hash_request_metadata(
            request.headers.get("user-agent", "")
        ),
    )


def _translate_auth_error(
    exc: UserAuthenticationError,
) -> HTTPException:
    return auth_error(
        exc.status_code,
        exc.code,
        exc.message,
    )


async def require_user(
    session: Any,
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

    async with StateSession() as session:
        if not await registration_enabled(session):
            raise auth_error(
                403,
                "REGISTRATION_DISABLED",
                "当前站点未开放自助注册",
            )
        ip_hash, agent_hash = _session_metadata(request)
        try:
            result = await register_user(
                session,
                username=username,
                username_normalized=normalized,
                password=password,
                created_ip_hash=ip_hash,
                user_agent_hash=agent_hash,
            )
        except UserAuthenticationError as exc:
            raise _translate_auth_error(exc) from exc

    set_user_session_cookie(
        request,
        response,
        result.token,
    )
    return user_dict(result.user)


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

    async with StateSession() as session:
        ip_hash, agent_hash = _session_metadata(request)
        try:
            result = await login_user(
                session,
                username_normalized=normalized,
                password=payload.password,
                created_ip_hash=ip_hash,
                user_agent_hash=agent_hash,
            )
        except UserAuthenticationError as exc:
            raise _translate_auth_error(exc) from exc

    set_user_session_cookie(
        request,
        response,
        result.token,
    )
    return user_dict(result.user)


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
):
    validate_request_origin(request)
    async with StateSession() as session:
        await logout_user(
            session,
            token=request.cookies.get(USER_SESSION_COOKIE),
        )
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

    async with StateSession() as session:
        _, authenticated = await require_user(
            session,
            request,
        )
        ip_hash, agent_hash = _session_metadata(request)
        try:
            result = await change_user_password(
                session,
                user_id=authenticated.id,
                current_password=payload.current_password,
                new_password=new_password,
                created_ip_hash=ip_hash,
                user_agent_hash=agent_hash,
            )
        except UserAuthenticationError as exc:
            raise _translate_auth_error(exc) from exc

    set_user_session_cookie(
        request,
        response,
        result.token,
    )
    return {"ok": True}
