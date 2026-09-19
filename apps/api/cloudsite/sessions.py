"""HTTP/compatibility shim for Users-owned server-side sessions."""

import hashlib
import hmac
from datetime import datetime

from fastapi import Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .database import StateSession
from .modules.users.contracts.public import (
    AuthenticatedUserView,
    SESSION_RETENTION_DAYS,
    SESSION_TOUCH_INTERVAL,
    USER_SESSION_MAX_AGE,
    UserSessionValidationError,
    UserSessionView,
    as_utc,
    cleanup_expired_user_sessions_state,
    create_user_session_state,
    hash_session_token,
    resolve_user_session_state,
    revoke_session_state,
    revoke_user_sessions_state,
    validate_user_session_state,
)
from .request_context import request_is_https


USER_SESSION_COOKIE = "cloudsite_user_session"
SESSION_CLEANUP_SECONDS = 6 * 60 * 60

# Historical public name retained for callers/tests.
SessionValidationError = UserSessionValidationError


def hash_request_metadata(value: str) -> str | None:
    value = value.strip()
    if not value:
        return None
    return hmac.new(
        settings.secret_key.encode(),
        value.encode(),
        hashlib.sha256,
    ).hexdigest()


async def create_user_session(
    session: AsyncSession,
    user_id: int,
    now: datetime | None = None,
    request: Request | None = None,
) -> tuple[UserSessionView, str]:
    return await create_user_session_state(
        session,
        user_id=user_id,
        now=now,
        created_ip_hash=hash_request_metadata(
            request.client.host
            if request and request.client
            else ""
        ),
        user_agent_hash=hash_request_metadata(
            request.headers.get("user-agent", "")
            if request
            else ""
        ),
    )


async def resolve_user_session(
    session: AsyncSession,
    token: str | None,
    now: datetime | None = None,
) -> tuple[UserSessionView, AuthenticatedUserView] | None:
    return await resolve_user_session_state(
        session,
        token=token,
        now=now,
    )


async def validate_user_session(
    session: AsyncSession,
    token: str | None,
    now: datetime | None = None,
) -> tuple[UserSessionView, AuthenticatedUserView]:
    return await validate_user_session_state(
        session,
        token=token,
        now=now,
    )


async def revoke_session(
    session: AsyncSession,
    token: str | None,
    now: datetime | None = None,
) -> None:
    await revoke_session_state(
        session,
        token=token,
        now=now,
    )


async def revoke_user_sessions(
    session: AsyncSession,
    user_id: int,
    now: datetime | None = None,
) -> None:
    await revoke_user_sessions_state(
        session,
        user_id=user_id,
        now=now,
    )


async def cleanup_expired_user_sessions(
    now: datetime | None = None,
    retention_days: int = SESSION_RETENTION_DAYS,
) -> int:
    async with StateSession() as session:
        return await cleanup_expired_user_sessions_state(
            session,
            now=now,
            retention_days=retention_days,
        )


def set_user_session_cookie(
    request: Request,
    response: Response,
    token: str,
) -> None:
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
    response.delete_cookie(
        USER_SESSION_COOKIE,
        path="/",
        httponly=True,
        samesite="lax",
    )


__all__ = [
    "AuthenticatedUserView",
    "SESSION_CLEANUP_SECONDS",
    "SESSION_RETENTION_DAYS",
    "SESSION_TOUCH_INTERVAL",
    "SessionValidationError",
    "USER_SESSION_COOKIE",
    "USER_SESSION_MAX_AGE",
    "UserSessionView",
    "as_utc",
    "cleanup_expired_user_sessions",
    "clear_user_session_cookie",
    "create_user_session",
    "hash_request_metadata",
    "hash_session_token",
    "resolve_user_session",
    "revoke_session",
    "revoke_user_sessions",
    "set_user_session_cookie",
    "validate_user_session",
]
