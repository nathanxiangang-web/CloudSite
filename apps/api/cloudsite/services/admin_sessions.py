"""Durable, revocable administrator sessions.

The raw bearer value is returned only when a session is issued.  State stores
only a SHA-256 digest, so database inspection cannot replay an active cookie.
Route integration is intentionally separate because upstream administrator
authority must be proven by a version-supported AList response field.
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AdminSession, SystemSetting

ADMIN_SESSION_EPOCH_KEY = "admin_session_epoch"
DEFAULT_ADMIN_SESSION_SECONDS = 86400


class AdminSessionError(Exception):
    code = "ADMIN_SESSION_INVALID"


class AdminSessionInvalid(AdminSessionError):
    pass


class AdminSessionExpired(AdminSessionError):
    code = "ADMIN_SESSION_EXPIRED"


class AdminSessionRevoked(AdminSessionError):
    code = "ADMIN_SESSION_REVOKED"


@dataclass(frozen=True, slots=True)
class IssuedAdminSession:
    token: str
    session: AdminSession


def hash_admin_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _optional_context_hash(value: str | None) -> str | None:
    normalized = (value or "").strip()
    return hash_admin_session_token(normalized) if normalized else None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def current_admin_session_epoch(state: AsyncSession) -> int:
    row = await state.get(SystemSetting, ADMIN_SESSION_EPOCH_KEY)
    if row is None:
        return 1
    try:
        return max(1, int(row.value))
    except (TypeError, ValueError):
        raise AdminSessionInvalid("administrator session epoch is invalid") from None


async def issue_admin_session(
    state: AsyncSession,
    *,
    principal: str,
    authority: str,
    ttl_seconds: int = DEFAULT_ADMIN_SESSION_SECONDS,
    created_ip: str | None = None,
    user_agent: str | None = None,
    now: datetime | None = None,
) -> IssuedAdminSession:
    principal = principal.strip()
    authority = authority.strip()
    if not principal:
        raise AdminSessionInvalid("administrator principal is required")
    if not authority:
        raise AdminSessionInvalid("administrator authority evidence is required")
    if ttl_seconds < 60 or ttl_seconds > 7 * 86400:
        raise AdminSessionInvalid("administrator session lifetime is out of range")

    issued_at = _utc(now or datetime.now(timezone.utc))
    token = secrets.token_urlsafe(32)
    row = AdminSession(
        session_token_hash=hash_admin_session_token(token),
        principal=principal,
        authority=authority,
        created_at=issued_at,
        last_seen_at=issued_at,
        expires_at=issued_at + timedelta(seconds=ttl_seconds),
        epoch=await current_admin_session_epoch(state),
        created_ip_hash=_optional_context_hash(created_ip),
        user_agent_hash=_optional_context_hash(user_agent),
    )
    state.add(row)
    await state.flush()
    return IssuedAdminSession(token=token, session=row)


async def validate_admin_session(
    state: AsyncSession,
    token: str | None,
    *,
    now: datetime | None = None,
    touch: bool = True,
) -> AdminSession:
    if not token:
        raise AdminSessionInvalid("administrator session token is missing")
    row = await state.scalar(
        select(AdminSession).where(
            AdminSession.session_token_hash == hash_admin_session_token(token)
        )
    )
    if row is None:
        raise AdminSessionInvalid("administrator session token is invalid")
    if row.revoked_at is not None:
        raise AdminSessionRevoked("administrator session has been revoked")
    if row.epoch != await current_admin_session_epoch(state):
        raise AdminSessionRevoked("administrator session epoch is obsolete")
    checked_at = _utc(now or datetime.now(timezone.utc))
    if _utc(row.expires_at) <= checked_at:
        raise AdminSessionExpired("administrator session has expired")
    if touch:
        row.last_seen_at = checked_at
        await state.flush()
    return row


async def revoke_admin_session(
    state: AsyncSession,
    token: str | None,
    *,
    reason: str = "logout",
    now: datetime | None = None,
) -> bool:
    if not token:
        return False
    row = await state.scalar(
        select(AdminSession).where(
            AdminSession.session_token_hash == hash_admin_session_token(token)
        )
    )
    if row is None:
        return False
    if row.revoked_at is None:
        row.revoked_at = _utc(now or datetime.now(timezone.utc))
        row.revocation_reason = reason.strip()[:40] or "revoked"
        await state.flush()
    return True
