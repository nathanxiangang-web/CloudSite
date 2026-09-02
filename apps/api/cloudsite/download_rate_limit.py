import asyncio
import hashlib
import hmac
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Request
from sqlalchemy import delete, select, text

from .config import settings
from .database import StateSession
from .models import DownloadRateLimit, utcnow
from .request_context import is_trusted_proxy, normalize_ip


DOWNLOAD_RATE_MAX_ATTEMPTS = 5
DOWNLOAD_RATE_WINDOW_SECONDS = 60
DOWNLOAD_RATE_BLOCK_SECONDS = 60
DOWNLOAD_RATE_CLEANUP_SECONDS = 6 * 60 * 60

# A fixed lock stripe set prevents an unbounded per-IP lock cache. SQLite's
# BEGIN IMMEDIATE below remains the cross-worker serialization boundary.
_RATE_LOCKS = tuple(asyncio.Lock() for _ in range(256))


@dataclass(frozen=True)
class DownloadRateDecision:
    allowed: bool
    retry_after: int = 0
    blocked_until: datetime | None = None
    ip_key: str = ""
    newly_blocked: bool = False


def get_effective_client_ip(request: Request) -> str:
    peer = normalize_ip(request.client.host if request.client else "127.0.0.1")
    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded or not is_trusted_proxy(peer):
        return peer

    try:
        chain = [normalize_ip(item) for item in forwarded.split(",") if item.strip()]
    except ValueError:
        return peer
    if not chain:
        return peer

    # Walk from the socket peer towards the browser. Trusted hops are removed
    # from the right; the first untrusted hop is the effective client.
    for address in reversed([*chain, peer]):
        if not is_trusted_proxy(address):
            return address
    return chain[0]


def hash_ip(address: str) -> str:
    purpose_key = hmac.new(
        settings.secret_key.encode("utf-8"),
        b"cloudsite-download-rate-ip-v1",
        hashlib.sha256,
    ).digest()
    return hmac.new(purpose_key, normalize_ip(address).encode("utf-8"), hashlib.sha256).hexdigest()


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _encode_time(value: datetime) -> str:
    return _as_utc(value).isoformat().replace("+00:00", "Z")


def _decode_hits(value: str) -> list[datetime]:
    try:
        raw = json.loads(value)
        if not isinstance(raw, list):
            return []
        hits = []
        for item in raw:
            if not isinstance(item, str):
                continue
            hits.append(_as_utc(datetime.fromisoformat(item.replace("Z", "+00:00"))))
        return hits
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


async def check_download_rate(address: str, now: datetime | None = None) -> DownloadRateDecision:
    current = _as_utc(now or utcnow())
    ip_key = hash_ip(address)
    lock = _RATE_LOCKS[int(ip_key[:2], 16)]
    async with lock:
        async with StateSession() as session:
            # Prevent separate API workers from reading and updating the same
            # SQLite state concurrently. The transaction is intentionally tiny.
            await session.execute(text("BEGIN IMMEDIATE"))
            row = await session.scalar(select(DownloadRateLimit).where(DownloadRateLimit.ip_key == ip_key))
            if row is None:
                row = DownloadRateLimit(
                    ip_key=ip_key,
                    recent_hits_json="[]",
                    created_at=current,
                    updated_at=current,
                )
                session.add(row)

            if row.blocked_until and current < _as_utc(row.blocked_until):
                retry_after = max(1, math.ceil((_as_utc(row.blocked_until) - current).total_seconds()))
                await session.commit()
                return DownloadRateDecision(False, retry_after, _as_utc(row.blocked_until), ip_key)

            if row.blocked_until:
                row.blocked_until = None
                row.recent_hits_json = "[]"

            window_start = current - timedelta(seconds=DOWNLOAD_RATE_WINDOW_SECONDS)
            hits = [hit for hit in _decode_hits(row.recent_hits_json) if hit > window_start]
            if len(hits) < DOWNLOAD_RATE_MAX_ATTEMPTS:
                hits.append(current)
                row.recent_hits_json = json.dumps([_encode_time(hit) for hit in hits[-DOWNLOAD_RATE_MAX_ATTEMPTS:]])
                row.updated_at = current
                await session.commit()
                return DownloadRateDecision(True, ip_key=ip_key)

            row.blocked_until = current + timedelta(seconds=DOWNLOAD_RATE_BLOCK_SECONDS)
            row.recent_hits_json = json.dumps([_encode_time(hit) for hit in hits[-DOWNLOAD_RATE_MAX_ATTEMPTS:]])
            row.updated_at = current
            await session.commit()
            return DownloadRateDecision(
                False,
                DOWNLOAD_RATE_BLOCK_SECONDS,
                _as_utc(row.blocked_until),
                ip_key,
                newly_blocked=True,
            )


async def cleanup_download_rate_limits(now: datetime | None = None) -> int:
    current = _as_utc(now or utcnow())
    cutoff = current - timedelta(hours=24)
    async with StateSession() as session:
        result = await session.execute(
            delete(DownloadRateLimit).where(
                DownloadRateLimit.updated_at < cutoff,
                (DownloadRateLimit.blocked_until.is_(None)) | (DownloadRateLimit.blocked_until <= current),
            )
        )
        await session.commit()
        return int(result.rowcount or 0)


def rate_limit_payload(decision: DownloadRateDecision) -> dict:
    return {
        "code": "DOWNLOAD_RATE_LIMITED",
        "message": "下载过于频繁，请稍后再试",
        "retry_after": decision.retry_after,
        "blocked_until": _encode_time(decision.blocked_until) if decision.blocked_until else None,
    }
