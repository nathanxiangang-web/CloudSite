import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Request, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import User, UserSession, utcnow


USER_SESSION_COOKIE = "cloudsite_user_session"
USER_SESSION_MAX_AGE = 30 * 24 * 60 * 60
SESSION_TOUCH_INTERVAL = timedelta(minutes=5)


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_user_session(
    session: AsyncSession, user_id: int, now: datetime | None = None
) -> tuple[UserSession, str]:
    now = now or utcnow()
    token = secrets.token_urlsafe(48)
    row = UserSession(
        session_token_hash=hash_session_token(token),
        user_id=user_id,
        created_at=now,
        expires_at=now + timedelta(seconds=USER_SESSION_MAX_AGE),
        last_seen_at=now,
    )
    session.add(row)
    await session.flush()
    return row, token


async def resolve_user_session(
    session: AsyncSession, token: str | None, now: datetime | None = None
) -> tuple[UserSession, User] | None:
    if not token:
        return None
    now = now or utcnow()
    result = await session.execute(
        select(UserSession, User)
        .join(User, User.id == UserSession.user_id)
        .where(
            UserSession.session_token_hash == hash_session_token(token),
            UserSession.revoked_at.is_(None),
        )
    )
    pair = result.first()
    if not pair:
        return None
    user_session, user = pair
    if as_utc(user_session.expires_at) <= as_utc(now) or user.status != "active":
        user_session.revoked_at = now
        return None
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


def set_user_session_cookie(request: Request, response: Response, token: str) -> None:
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https"
    response.set_cookie(
        USER_SESSION_COOKIE,
        token,
        max_age=USER_SESSION_MAX_AGE,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )


def clear_user_session_cookie(response: Response) -> None:
    response.delete_cookie(USER_SESSION_COOKIE, path="/", httponly=True, samesite="lax")
