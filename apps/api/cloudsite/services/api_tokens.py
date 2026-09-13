"""X2 API Token service.

Tokens are hashed (SHA-256) at rest. Scopes limit actions and object ranges.
Tokens can be revoked; revocation takes effect immediately.

Transaction ownership stays with the caller.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import APIToken, utcnow

TOKEN_ID_PREFIX = "at_"
_TOKEN_HEX_LEN = 32
_RAW_TOKEN_LEN = 48


def _as_aware_utc(value: datetime | None) -> datetime | None:
    """Normalize a datetime to aware UTC.

    SQLite returns naive datetimes for ``DateTime(timezone=True)`` columns even
    when aware UTC values were written, so a direct comparison against
    ``utcnow()`` raises ``TypeError: can't compare offset-naive and
    offset-aware datetimes``. Naive values are treated as UTC (consistent with
    the ``utcnow()`` default and existing rows written from UTC) and aware
    values are converted to UTC.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class APITokenError(Exception):
    """API token error base class."""


class TokenNotFound(APITokenError):
    def __init__(self, token_id: str):
        super().__init__(f"API token {token_id} not found")


class TokenInvalid(APITokenError):
    def __init__(self, message: str = "Invalid API token"):
        super().__init__(message)


class ScopeDenied(APITokenError):
    def __init__(self, scope: str):
        super().__init__(f"Token lacks required scope: {scope}")


@dataclass(frozen=True, slots=True)
class TokenSummary:
    token_id: str
    label: str
    scopes: list[str]
    status: str
    created_by: str
    expires_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime
    updated_at: datetime


def _new_token_id() -> str:
    return TOKEN_ID_PREFIX + secrets.token_hex(_TOKEN_HEX_LEN // 2)


def _generate_raw_token() -> str:
    return secrets.token_urlsafe(_RAW_TOKEN_LEN)


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


async def create_token(
    state: AsyncSession,
    label: str = "",
    scopes: list[str] | None = None,
    created_by: str = "",
    expires_at: datetime | None = None,
) -> tuple[str, APIToken]:
    raw_token = _generate_raw_token()
    token = APIToken(
        token_id=_new_token_id(),
        token_hash=_hash_token(raw_token),
        label=label,
        scopes=json.dumps(scopes or []),
        created_by=created_by,
        expires_at=_as_aware_utc(expires_at),
    )
    state.add(token)
    await state.flush()
    return raw_token, token


async def verify_token(
    state: AsyncSession,
    raw_token: str,
    required_scope: str | None = None,
) -> APIToken:
    token_hash = _hash_token(raw_token)
    result = await state.execute(
        select(APIToken).where(APIToken.token_hash == token_hash)
    )
    token = result.scalar_one_or_none()
    if not token:
        raise TokenInvalid()
    if token.status != "active":
        raise TokenInvalid("Token revoked")
    expires_at = _as_aware_utc(token.expires_at)
    if expires_at is not None and expires_at < utcnow():
        raise TokenInvalid("Token expired")
    if required_scope:
        scopes = json.loads(token.scopes)
        if required_scope not in scopes and "*" not in scopes:
            raise ScopeDenied(required_scope)
    token.last_used_at = utcnow()
    await state.flush()
    return token


async def revoke_token(state: AsyncSession, token_id: str) -> APIToken:
    token = await state.get(APIToken, token_id)
    if not token:
        raise TokenNotFound(token_id)
    token.status = "revoked"
    token.updated_at = utcnow()
    await state.flush()
    return token


async def list_tokens(state: AsyncSession, status: str | None = None) -> list[TokenSummary]:
    stmt = select(APIToken).order_by(APIToken.created_at.desc())
    if status:
        stmt = stmt.where(APIToken.status == status)
    result = await state.execute(stmt)
    tokens = result.scalars().all()
    return [
        TokenSummary(
            token_id=t.token_id,
            label=t.label,
            scopes=json.loads(t.scopes),
            status=t.status,
            created_by=t.created_by,
            expires_at=t.expires_at,
            last_used_at=t.last_used_at,
            created_at=t.created_at,
            updated_at=t.updated_at,
        )
        for t in tokens
    ]


async def get_token(state: AsyncSession, token_id: str) -> TokenSummary:
    token = await state.get(APIToken, token_id)
    if not token:
        raise TokenNotFound(token_id)
    return TokenSummary(
        token_id=token.token_id,
        label=token.label,
        scopes=json.loads(token.scopes),
        status=token.status,
        created_by=token.created_by,
        expires_at=token.expires_at,
        last_used_at=token.last_used_at,
        created_at=token.created_at,
        updated_at=token.updated_at,
    )
