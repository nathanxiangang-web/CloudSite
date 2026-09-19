"""Users-owned server-side session lifecycle."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure.models import User, UserSession, utcnow


USER_SESSION_MAX_AGE = 7 * 24 * 60 * 60
SESSION_TOUCH_INTERVAL = timedelta(minutes=5)
SESSION_RETENTION_DAYS = 7


class UserSessionValidationError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class UserSessionView:
    id: int
    user_id: int
    created_at: datetime
    expires_at: datetime
    last_seen_at: datetime
    revoked_at: datetime | None
    created_ip_hash: str | None
    user_agent_hash: str | None


@dataclass(frozen=True, slots=True)
class AuthenticatedUserView:
    id: int
    username: str
    status: str
    created_at: datetime
    last_login_at: datetime | None
    password_changed_at: datetime | None
    disabled_at: datetime | None
    deleted_at: datetime | None
    created_by_admin: bool
    role: str


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _session_view(row: UserSession) -> UserSessionView:
    return UserSessionView(
        id=row.id,
        user_id=row.user_id,
        created_at=row.created_at,
        expires_at=row.expires_at,
        last_seen_at=row.last_seen_at,
        revoked_at=row.revoked_at,
        created_ip_hash=row.created_ip_hash,
        user_agent_hash=row.user_agent_hash,
    )


def _user_view(row: User) -> AuthenticatedUserView:
    return AuthenticatedUserView(
        id=row.id,
        username=row.username,
        status=row.status,
        created_at=row.created_at,
        last_login_at=row.last_login_at,
        password_changed_at=row.password_changed_at,
        disabled_at=row.disabled_at,
        deleted_at=row.deleted_at,
        created_by_admin=bool(row.created_by_admin),
        role=row.role,
    )


async def create_user_session_state(
    state: AsyncSession,
    *,
    user_id: int,
    now: datetime | None = None,
    created_ip_hash: str | None = None,
    user_agent_hash: str | None = None,
) -> tuple[UserSessionView, str]:
    current = now or utcnow()
    token = secrets.token_urlsafe(48)
    row = UserSession(
        session_token_hash=hash_session_token(token),
        user_id=user_id,
        created_at=current,
        expires_at=current + timedelta(seconds=USER_SESSION_MAX_AGE),
        last_seen_at=current,
        created_ip_hash=created_ip_hash,
        user_agent_hash=user_agent_hash,
    )
    state.add(row)
    await state.flush()
    return _session_view(row), token


async def validate_user_session_state(
    state: AsyncSession,
    *,
    token: str | None,
    now: datetime | None = None,
) -> tuple[UserSessionView, AuthenticatedUserView]:
    if not token:
        raise UserSessionValidationError(
            401,
            "AUTH_REQUIRED",
            "请先登录",
        )

    current = now or utcnow()
    result = await state.execute(
        select(UserSession, User)
        .outerjoin(User, User.id == UserSession.user_id)
        .where(
            UserSession.session_token_hash
            == hash_session_token(token)
        )
    )
    pair = result.first()
    if not pair:
        raise UserSessionValidationError(
            401,
            "SESSION_INVALID",
            "登录状态无效，请重新登录",
        )

    user_session, user = pair
    if user is None or user.deleted_at is not None:
        if user_session.revoked_at is None:
            user_session.revoked_at = current
        raise UserSessionValidationError(
            401,
            "USER_DELETED",
            "账号不存在或已被删除",
        )
    if user.status != "active":
        if user_session.revoked_at is None:
            user_session.revoked_at = current
        raise UserSessionValidationError(
            403,
            "USER_DISABLED",
            "当前账号已被停用",
        )
    if user_session.revoked_at is not None:
        raise UserSessionValidationError(
            401,
            "SESSION_REVOKED",
            "登录状态已失效，请重新登录",
        )
    if as_utc(user_session.expires_at) <= as_utc(current):
        user_session.revoked_at = current
        raise UserSessionValidationError(
            401,
            "SESSION_EXPIRED",
            "登录已过期，请重新登录",
        )
    if (
        as_utc(user_session.last_seen_at)
        <= as_utc(current) - SESSION_TOUCH_INTERVAL
    ):
        user_session.last_seen_at = current

    return _session_view(user_session), _user_view(user)


async def resolve_user_session_state(
    state: AsyncSession,
    *,
    token: str | None,
    now: datetime | None = None,
) -> tuple[UserSessionView, AuthenticatedUserView] | None:
    try:
        return await validate_user_session_state(
            state,
            token=token,
            now=now,
        )
    except UserSessionValidationError:
        return None


async def revoke_session_state(
    state: AsyncSession,
    *,
    token: str | None,
    now: datetime | None = None,
) -> None:
    if not token:
        return
    await state.execute(
        update(UserSession)
        .where(
            UserSession.session_token_hash
            == hash_session_token(token),
            UserSession.revoked_at.is_(None),
        )
        .values(revoked_at=now or utcnow())
    )


async def revoke_user_sessions_state(
    state: AsyncSession,
    *,
    user_id: int,
    now: datetime | None = None,
) -> None:
    await state.execute(
        update(UserSession)
        .where(
            UserSession.user_id == user_id,
            UserSession.revoked_at.is_(None),
        )
        .values(revoked_at=now or utcnow())
    )


async def cleanup_expired_user_sessions_state(
    state: AsyncSession,
    *,
    now: datetime | None = None,
    retention_days: int = SESSION_RETENTION_DAYS,
) -> int:
    current = as_utc(now or utcnow())
    cutoff = current - timedelta(days=max(0, retention_days))
    result = await state.execute(
        delete(UserSession).where(
            or_(
                UserSession.expires_at < cutoff,
                UserSession.revoked_at < cutoff,
            )
        )
    )
    await state.commit()
    return int(result.rowcount or 0)


__all__ = [
    "AuthenticatedUserView",
    "SESSION_RETENTION_DAYS",
    "SESSION_TOUCH_INTERVAL",
    "USER_SESSION_MAX_AGE",
    "UserSessionValidationError",
    "UserSessionView",
    "as_utc",
    "cleanup_expired_user_sessions_state",
    "create_user_session_state",
    "hash_session_token",
    "resolve_user_session_state",
    "revoke_session_state",
    "revoke_user_sessions_state",
    "validate_user_session_state",
]
