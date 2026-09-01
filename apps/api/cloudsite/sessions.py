import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Request, Response
from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .database import StateSession
from .models import User, UserSession, utcnow
from .request_context import request_is_https
from .config import settings


USER_SESSION_COOKIE = "cloudsite_user_session"
USER_SESSION_MAX_AGE = 30 * 24 * 60 * 60
SESSION_TOUCH_INTERVAL = timedelta(minutes=5)
SESSION_RETENTION_DAYS = 7
SESSION_CLEANUP_SECONDS = 6 * 60 * 60


class SessionValidationError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hash_request_metadata(value: str) -> str | None:
    value = value.strip()
    if not value:
        return None
    return hmac.new(settings.secret_key.encode(), value.encode(), hashlib.sha256).hexdigest()


async def create_user_session(
    session: AsyncSession, user_id: int, now: datetime | None = None, request: Request | None = None
) -> tuple[UserSession, str]:
    now = now or utcnow()
    token = secrets.token_urlsafe(48)
    row = UserSession(
        session_token_hash=hash_session_token(token),
        user_id=user_id,
        created_at=now,
        expires_at=now + timedelta(seconds=USER_SESSION_MAX_AGE),
        last_seen_at=now,
        created_ip_hash=hash_request_metadata(request.client.host if request and request.client else ""),
        user_agent_hash=hash_request_metadata(request.headers.get("user-agent", "") if request else ""),
    )
    session.add(row)
    await session.flush()
    return row, token


async def resolve_user_session(
    session: AsyncSession, token: str | None, now: datetime | None = None
) -> tuple[UserSession, User] | None:
    try:
        return await validate_user_session(session, token, now)
    except SessionValidationError:
        return None


async def validate_user_session(
    session: AsyncSession, token: str | None, now: datetime | None = None
) -> tuple[UserSession, User]:
    if not token:
        raise SessionValidationError(401, "AUTH_REQUIRED", "请先登录")
    now = now or utcnow()
    result = await session.execute(
        select(UserSession, User)
        .outerjoin(User, User.id == UserSession.user_id)
        .where(UserSession.session_token_hash == hash_session_token(token))
    )
    pair = result.first()
    if not pair:
        raise SessionValidationError(401, "SESSION_INVALID", "登录状态无效，请重新登录")
    user_session, user = pair
    if user is None or user.deleted_at is not None:
        if user_session.revoked_at is None:
            user_session.revoked_at = now
        raise SessionValidationError(401, "USER_DELETED", "账号不存在或已被删除")
    if user.status != "active":
        if user_session.revoked_at is None:
            user_session.revoked_at = now
        raise SessionValidationError(403, "USER_DISABLED", "当前账号已被停用")
    if user_session.revoked_at is not None:
        raise SessionValidationError(401, "SESSION_REVOKED", "登录状态已失效，请重新登录")
    if as_utc(user_session.expires_at) <= as_utc(now):
        user_session.revoked_at = now
        raise SessionValidationError(401, "SESSION_EXPIRED", "登录已过期，请重新登录")
    if as_utc(user_session.last_seen_at) <= as_utc(now) - SESSION_TOUCH_INTERVAL:
        user_session.last_seen_at = now
    return user_session, user


async def revoke_session(session: AsyncSession, token: str | None, now: datetime | None = None) -> None:
    if not token:
        return
    await session.execute(
        update(UserSession)
        .where(
            UserSession.session_token_hash == hash_session_token(token),
            UserSession.revoked_at.is_(None),
        )
        .values(revoked_at=now or utcnow())
    )


async def revoke_user_sessions(session: AsyncSession, user_id: int, now: datetime | None = None) -> None:
    await session.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=now or utcnow())
    )


async def cleanup_expired_user_sessions(
    now: datetime | None = None,
    retention_days: int = SESSION_RETENTION_DAYS,
) -> int:
    current = as_utc(now or utcnow())
    cutoff = current - timedelta(days=max(0, retention_days))
    async with StateSession() as session:
        result = await session.execute(
            delete(UserSession).where(
                or_(
                    UserSession.expires_at < cutoff,
                    UserSession.revoked_at < cutoff,
                )
            )
        )
        await session.commit()
        return int(result.rowcount or 0)


def set_user_session_cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie(
        USER_SESSION_COOKIE,
        token,
        max_age=USER_SESSION_MAX_AGE,
        httponly=True,
        secure=request_is_https(request),
        samesite="lax",
        path="/",
    )


def clear_user_session_cookie(response: Response) -> None:
    response.delete_cookie(USER_SESSION_COOKIE, path="/", httponly=True, samesite="lax")
