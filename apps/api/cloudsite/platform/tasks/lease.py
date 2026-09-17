from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

DEFAULT_LEASE_TTL = timedelta(minutes=5)
HEARTBEAT_INTERVAL = timedelta(minutes=1)


def generate_lease_owner() -> str:
    return f'worker-{secrets.token_hex(8)}'


def compute_lease_expiry(ttl: timedelta = DEFAULT_LEASE_TTL, *, now: datetime | None = None) -> datetime:
    base = now or datetime.now(timezone.utc)
    return base + ttl


def is_expired(expires_at: datetime | None, *, now: datetime | None = None) -> bool:
    if expires_at is None:
        return True
    base = now or datetime.now(timezone.utc)
    return base > expires_at


def renew_lease(expires_at: datetime, ttl: timedelta = DEFAULT_LEASE_TTL, *, now: datetime | None = None) -> datetime:
    base = now or datetime.now(timezone.utc)
    return max(expires_at, base) + ttl


__all__ = [
    'DEFAULT_LEASE_TTL',
    'HEARTBEAT_INTERVAL',
    'generate_lease_owner',
    'compute_lease_expiry',
    'is_expired',
    'renew_lease',
]
