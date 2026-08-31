import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .database import StateSession
from .models import OperationLog, User, utcnow
from .schemas import UserLoginInput, UserPasswordChangeInput, UserRegisterInput
from .sessions import (
    USER_SESSION_COOKIE,
    clear_user_session_cookie,
    create_user_session,
    revoke_session,
    revoke_user_sessions,
    set_user_session_cookie,
    SessionValidationError,
    validate_user_session,
)


router = APIRouter(prefix="/api/auth", tags=["public-auth"])
password_hash = PasswordHash.recommended()
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{3,32}$")


def auth_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def validate_username(username: str) -> tuple[str, str]:
    if username != username.strip() or not USERNAME_PATTERN.fullmatch(username):
        raise auth_error(400, "USERNAME_INVALID", "用户名须为 3～32 位，仅允许字母、数字、下划线和短横线")
    return username, username.lower()


def validate_password(value: str, *, field_name: str = "密码") -> str:
    if len(value) < 8 or len(value) > 72:
        raise auth_error(400, "PASSWORD_INVALID", f"{field_name}长度须为 8～72 位")
    return value


def verify_password(value: str, encoded: str) -> bool:
    try:
        return password_hash.verify(value, encoded)
    except Exception:
        return False


def user_dict(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "status": "deleted" if user.deleted_at is not None else user.status,
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
    supplied = request.headers.get("origin") or request.headers.get("referer")
    if not supplied:
        return
    supplied_origin = _origin(supplied)
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    host = request.headers.get("x-forwarded-host", request.headers.get("host", "")).split(",")[0].strip()
    allowed = {_origin(value) for value in settings.cors_origin_list}
    if host:
        allowed.add(_origin(f"{scheme}://{host}"))
    if not supplied_origin or supplied_origin not in allowed:
        raise auth_error(403, "CSRF_ORIGIN_INVALID", "请求来源校验失败")


async def require_user(session: AsyncSession, request: Request) -> tuple[object, User]:
    try:
        return await validate_user_session(session, request.cookies.get(USER_SESSION_COOKIE))
    except SessionValidationError as exc:
        raise auth_error(exc.status_code, exc.code, exc.message) from exc


@router.post("/register", status_code=201)
async def register(payload: UserRegisterInput, request: Request, response: Response):
    validate_request_origin(request)
    username, normalized = validate_username(payload.username)
    password = validate_password(payload.password)
    if password != payload.password_confirm:
        raise auth_error(400, "PASSWORD_CONFIRM_MISMATCH", "两次输入的密码不一致")
    now = utcnow()
    async with StateSession() as session:
        if await session.scalar(select(User.id).where(User.username_normalized == normalized)):
            raise auth_error(409, "USERNAME_EXISTS", "用户名已存在")
        user = User(
            username=username,
            username_normalized=normalized,
            password_hash=password_hash.hash(password),
            status="active",
            created_at=now,
            updated_at=now,
            last_login_at=now,
        )
        session.add(user)
        try:
            await session.flush()
            _, token = await create_user_session(session, user.id, now, request)
            session.add(OperationLog(level="INFO", module="auth", action="user_registered", message=f"用户 {user.username} 完成注册"))
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise auth_error(409, "USERNAME_EXISTS", "用户名已存在") from exc
        await session.refresh(user)
    set_user_session_cookie(request, response, token)
    return user_dict(user)


@router.post("/login")
async def login(payload: UserLoginInput, request: Request, response: Response):
    validate_request_origin(request)
    try:
        _, normalized = validate_username(payload.username)
    except HTTPException:
        normalized = ""
    async with StateSession() as session:
        user = await session.scalar(select(User).where(User.username_normalized == normalized)) if normalized else None
        if not user or user.deleted_at is not None or not verify_password(payload.password, user.password_hash):
            session.add(OperationLog(level="WARNING", module="auth", action="user_login_failed", message="前台用户登录失败"))
            await session.commit()
            raise auth_error(401, "INVALID_CREDENTIALS", "用户名或密码错误")
        if user.status != "active":
            raise auth_error(403, "USER_DISABLED", "当前账号已被停用")
        now = utcnow()
        user.last_login_at = now
        _, token = await create_user_session(session, user.id, now, request)
        session.add(OperationLog(level="INFO", module="auth", action="user_login_success", message=f"用户 {user.username} 登录成功"))
        await session.commit()
        await session.refresh(user)
    set_user_session_cookie(request, response, token)
    return user_dict(user)


@router.post("/logout")
async def logout(request: Request, response: Response):
    validate_request_origin(request)
    async with StateSession() as session:
        await revoke_session(session, request.cookies.get(USER_SESSION_COOKIE))
        await session.commit()
    clear_user_session_cookie(response)
    return {"ok": True}


@router.get("/me")
async def me(request: Request):
    async with StateSession() as session:
        _, user = await require_user(session, request)
        await session.commit()
        return {"authenticated": True, "user": user_dict(user)}


@router.post("/change-password")
async def change_password(payload: UserPasswordChangeInput, request: Request, response: Response):
    validate_request_origin(request)
    new_password = validate_password(payload.new_password, field_name="新密码")
    if new_password != payload.new_password_confirm:
        raise auth_error(400, "PASSWORD_CONFIRM_MISMATCH", "两次输入的新密码不一致")
    async with StateSession() as session:
        _, user = await require_user(session, request)
        if not verify_password(payload.current_password, user.password_hash):
            raise auth_error(400, "CURRENT_PASSWORD_INVALID", "当前密码错误")
        now = utcnow()
        user.password_hash = password_hash.hash(new_password)
        user.password_changed_at = now
        user.updated_at = now
        await revoke_user_sessions(session, user.id, now)
        _, token = await create_user_session(session, user.id, now, request)
        session.add(OperationLog(level="INFO", module="auth", action="password_changed", message=f"用户 {user.username} 修改密码"))
        await session.commit()
    set_user_session_cookie(request, response, token)
    return {"ok": True}
