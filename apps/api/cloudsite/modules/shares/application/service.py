"""Shares application boundary.

Owns Share/ShareVerifyAttempt persistence-facing lifecycle operations while
exposing persistence-neutral ShareView objects to routers and other modules.
Target/scope resolution remains on the legacy compatibility edge during this
migration step.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, desc, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ....platform.db import state_session
from ....platform.observability import write_operation_log
from ..domain.code import generate_share_code, hash_share_code
from ..domain.views import ShareStatus, ShareView
from ..infrastructure.models import Share, ShareVerifyAttempt, utcnow


MAX_SHARE_DOWNLOADS = 404
SHARE_TOKEN_ALPHABET = (
    "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
)
DURATION_OPTIONS = {"5m", "1h", "6h", "24h", "7d", "permanent"}


class ShareError(Exception):
    pass


class ShareNotFound(ShareError):
    def __init__(self, token: str):
        super().__init__(f"share not found: {token}")
        self.token = token


class ShareValidationError(ShareError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def share_expires_at(
    duration: str,
    now: datetime | None = None,
) -> datetime | None:
    if duration not in DURATION_OPTIONS:
        raise ShareValidationError(
            "SHARE_DURATION_INVALID",
            "有效期选项无效",
        )
    current = now or utcnow()
    return {
        "5m": current + timedelta(minutes=5),
        "1h": current + timedelta(hours=1),
        "6h": current + timedelta(hours=6),
        "24h": current + timedelta(hours=24),
        "7d": current + timedelta(days=7),
        "permanent": None,
    }[duration]


def share_status(
    share: ShareView,
    target_valid: bool = True,
    now: datetime | None = None,
) -> ShareStatus:
    current = now or utcnow()
    expires_at = aware_utc(share.expires_at)
    if share.access_mode == "code" and not share.code_hash:
        return "migration_pending"
    if not share.enabled:
        return "cancelled"
    if expires_at and expires_at <= current:
        return "expired"
    if not target_valid:
        return "invalid_target"
    return "active"


def share_view(row: Share) -> ShareView:
    return ShareView(
        token=row.token,
        creator_user_id=row.creator_user_id,
        object_type=row.object_type,
        object_id=row.object_id,
        title=row.title,
        enabled=bool(row.enabled),
        access_mode=row.access_mode,
        code_hash=row.code_hash,
        code_version=int(row.code_version or 0),
        expires_at=row.expires_at,
        cancelled_at=row.cancelled_at,
        cancel_reason=row.cancel_reason,
        access_count=int(row.access_count or 0),
        view_count=int(row.view_count or 0),
        download_count=int(row.download_count or 0),
        last_accessed_at=row.last_accessed_at,
        last_downloaded_at=row.last_downloaded_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def share_payload(share: ShareView) -> dict:
    view_count = (
        share.view_count
        if share.view_count is not None
        else share.access_count
    )
    return {
        "token": share.token,
        "object_type": share.object_type,
        "object_id": share.object_id,
        "title": share.title,
        "enabled": share.enabled,
        "access_mode": share.access_mode,
        "has_code": bool(share.code_hash),
        "code_version": share.code_version,
        "expires_at": share.expires_at,
        "cancelled_at": share.cancelled_at,
        "cancel_reason": share.cancel_reason,
        "access_count": share.access_count,
        "view_count": view_count,
        "download_count": share.download_count,
        "download_limit": MAX_SHARE_DOWNLOADS,
        "remaining_downloads": max(
            MAX_SHARE_DOWNLOADS - share.download_count,
            0,
        ),
        "last_accessed_at": share.last_accessed_at,
        "last_downloaded_at": share.last_downloaded_at,
        "created_at": share.created_at,
        "updated_at": share.updated_at,
    }


async def _row(
    state: AsyncSession,
    token: str,
    *,
    owner_user_id: int | None = None,
) -> Share:
    row = await state.get(Share, token)
    if row is None or (
        owner_user_id is not None
        and row.creator_user_id != owner_user_id
    ):
        raise ShareNotFound(token)
    return row


async def get_share(
    state: AsyncSession,
    token: str,
) -> ShareView | None:
    row = await state.get(Share, token)
    return share_view(row) if row is not None else None


async def get_owned_share(
    state: AsyncSession,
    token: str,
    *,
    owner_user_id: int,
) -> ShareView:
    return share_view(
        await _row(
            state,
            token,
            owner_user_id=owner_user_id,
        )
    )


async def list_all_shares(
    state: AsyncSession,
) -> list[ShareView]:
    rows = list(
        (
            await state.scalars(
                select(Share).order_by(desc(Share.created_at))
            )
        ).all()
    )
    return [share_view(row) for row in rows]


async def list_owned_shares(
    state: AsyncSession,
    *,
    owner_user_id: int,
) -> list[ShareView]:
    rows = list(
        (
            await state.scalars(
                select(Share)
                .where(Share.creator_user_id == owner_user_id)
                .order_by(desc(Share.created_at))
            )
        ).all()
    )
    return [share_view(row) for row in rows]


async def record_share_access(
    state: AsyncSession,
    token: str,
    *,
    increment_view: bool,
) -> ShareView:
    row = await _row(state, token)
    if increment_view:
        row.view_count = int(row.view_count or 0) + 1
        row.access_count = row.view_count
    else:
        row.access_count = int(row.access_count or 0) + 1
    row.last_accessed_at = utcnow()
    await state.flush()
    return share_view(row)


async def cancel_share(
    state: AsyncSession,
    token: str,
    *,
    owner_user_id: int | None = None,
    reason: str = "manual",
) -> ShareView:
    row = await _row(
        state,
        token,
        owner_user_id=owner_user_id,
    )
    row.enabled = False
    row.cancelled_at = utcnow()
    row.cancel_reason = reason
    row.updated_at = row.cancelled_at
    await write_operation_log(
        state,
        module="share",
        action="share_cancelled",
        message=f"取消分享 {row.token}",
    )
    await state.flush()
    return share_view(row)


async def restore_share(
    state: AsyncSession,
    token: str,
    *,
    duration: str | None = None,
    owner_user_id: int | None = None,
) -> ShareView:
    row = await _row(
        state,
        token,
        owner_user_id=owner_user_id,
    )
    if int(row.download_count or 0) >= MAX_SHARE_DOWNLOADS:
        raise ShareValidationError(
            "SHARE_DOWNLOAD_LIMIT_REACHED",
            "已达到下载上限，不能恢复",
        )
    expires_at = aware_utc(row.expires_at)
    if expires_at and expires_at <= utcnow():
        if not duration:
            raise ShareValidationError(
                "SHARE_DURATION_REQUIRED",
                "过期分享恢复时需要重新选择有效期",
            )
        row.expires_at = share_expires_at(duration)
    row.enabled = True
    row.cancelled_at = None
    row.cancel_reason = None
    row.updated_at = utcnow()
    await write_operation_log(
        state,
        module="share",
        action="share_restored",
        message=f"恢复分享 {row.token}",
    )
    await state.flush()
    return share_view(row)


async def reset_share_code(
    state: AsyncSession,
    token: str,
    *,
    secret_key: str,
    owner_user_id: int | None = None,
) -> tuple[ShareView, str]:
    row = await _row(
        state,
        token,
        owner_user_id=owner_user_id,
    )
    if row.access_mode != "code":
        raise ShareValidationError(
            "SHARE_DIRECT_HAS_NO_CODE",
            "直下分享没有分享码",
        )
    code = generate_share_code()
    row.code_hash = hash_share_code(
        row.token,
        code,
        secret_key=secret_key,
    )
    row.code_version = max(int(row.code_version or 0), 0) + 1
    row.enabled = True
    row.cancelled_at = None
    row.cancel_reason = None
    row.updated_at = utcnow()
    await write_operation_log(
        state,
        module="share",
        action="share_code_reset",
        message=f"重置分享码 {row.token}",
    )
    await state.flush()
    return share_view(row), code


async def update_share_duration(
    state: AsyncSession,
    token: str,
    *,
    duration: str,
    owner_user_id: int | None = None,
) -> ShareView:
    row = await _row(
        state,
        token,
        owner_user_id=owner_user_id,
    )
    row.expires_at = share_expires_at(duration)
    row.updated_at = utcnow()
    await write_operation_log(
        state,
        module="share",
        action="share_updated",
        message=f"修改分享有效期 {row.token}",
    )
    await state.flush()
    return share_view(row)


async def delete_share(
    state: AsyncSession,
    token: str,
    *,
    owner_user_id: int | None = None,
    action: str = "share_deleted",
    message: str | None = None,
) -> None:
    row = await _row(
        state,
        token,
        owner_user_id=owner_user_id,
    )
    await write_operation_log(
        state,
        module="share",
        action=action,
        message=message or f"删除分享 {token}",
    )
    await state.delete(row)
    await state.flush()


async def reserve_share_download(
    state: AsyncSession,
    token: str,
) -> int:
    now = utcnow()
    result = await state.execute(
        text(
            "UPDATE shares "
            "SET download_count = download_count + 1, "
            "last_downloaded_at = :now, "
            "enabled = CASE "
            "WHEN download_count + 1 >= :max_downloads "
            "THEN 0 ELSE enabled END, "
            "cancelled_at = CASE "
            "WHEN download_count + 1 >= :max_downloads "
            "THEN :now ELSE cancelled_at END, "
            "cancel_reason = CASE "
            "WHEN download_count + 1 >= :max_downloads "
            "THEN 'download_limit' ELSE cancel_reason END, "
            "updated_at = :now "
            "WHERE token = :token "
            "AND enabled = 1 "
            "AND download_count < :max_downloads"
        ),
        {
            "token": token,
            "now": now,
            "max_downloads": MAX_SHARE_DOWNLOADS,
        },
    )
    if result.rowcount != 1:
        raise ShareValidationError(
            "SHARE_DOWNLOAD_LIMIT_REACHED",
            "分享下载次数已用完",
            status_code=410,
        )
    count = await state.scalar(
        select(Share.download_count).where(Share.token == token)
    )
    if int(count or 0) == MAX_SHARE_DOWNLOADS:
        await write_operation_log(
            state,
            module="share",
            action="share_download_limit_reached",
            message=f"分享 {token} 达到下载上限",
        )
    return int(count or 0)


def _verification_ip_hash(
    address: str,
    *,
    secret_key: str,
) -> str:
    return hmac.new(
        secret_key.encode(),
        f"share-ip:{address}".encode(),
        hashlib.sha256,
    ).hexdigest()


async def verify_attempt_failed(
    state: AsyncSession,
    share_token: str,
    address: str,
    *,
    secret_key: str,
) -> bool:
    key = _verification_ip_hash(address, secret_key=secret_key)
    now = utcnow()
    window_started = now - timedelta(minutes=10)
    row = await state.scalar(
        select(ShareVerifyAttempt).where(
            ShareVerifyAttempt.share_token == share_token,
            ShareVerifyAttempt.ip_hash == key,
        )
    )
    if (
        row is None
        or aware_utc(row.window_started_at) <= window_started
    ):
        state.add(
            ShareVerifyAttempt(
                share_token=share_token,
                ip_hash=key,
                fail_count=1,
                window_started_at=now,
                updated_at=now,
            )
        )
        return False

    row.fail_count += 1
    row.updated_at = now
    if row.fail_count >= 5:
        row.challenge_required_until = now + timedelta(minutes=10)
        return True
    return False


async def challenge_required(
    state: AsyncSession,
    share_token: str,
    address: str,
    *,
    secret_key: str,
) -> bool:
    row = await state.scalar(
        select(ShareVerifyAttempt).where(
            ShareVerifyAttempt.share_token == share_token,
            ShareVerifyAttempt.ip_hash
            == _verification_ip_hash(address, secret_key=secret_key),
        )
    )
    return bool(
        row
        and row.challenge_required_until
        and aware_utc(row.challenge_required_until) > utcnow()
    )


async def clear_verify_attempts(
    state: AsyncSession,
    share_token: str,
    address: str,
    *,
    secret_key: str,
) -> None:
    await state.execute(
        delete(ShareVerifyAttempt).where(
            ShareVerifyAttempt.share_token == share_token,
            ShareVerifyAttempt.ip_hash
            == _verification_ip_hash(address, secret_key=secret_key),
        )
    )


async def cleanup_share_verify_attempts(
    now: datetime | None = None,
) -> int:
    threshold = (now or utcnow()) - timedelta(hours=1)
    async with state_session() as state:
        result = await state.execute(
            delete(ShareVerifyAttempt).where(
                ShareVerifyAttempt.updated_at < threshold
            )
        )
        await state.commit()
        return int(result.rowcount or 0)


def generate_share_token(length: int = 12) -> str:
    return "".join(
        secrets.choice(SHARE_TOKEN_ALPHABET)
        for _ in range(length)
    )


__all__ = [
    "DURATION_OPTIONS",
    "MAX_SHARE_DOWNLOADS",
    "SHARE_TOKEN_ALPHABET",
    "ShareError",
    "ShareNotFound",
    "ShareValidationError",
    "ShareView",
    "aware_utc",
    "cancel_share",
    "challenge_required",
    "cleanup_share_verify_attempts",
    "clear_verify_attempts",
    "delete_share",
    "generate_share_token",
    "get_owned_share",
    "get_share",
    "list_all_shares",
    "list_owned_shares",
    "record_share_access",
    "reserve_share_download",
    "reset_share_code",
    "restore_share",
    "share_expires_at",
    "share_payload",
    "share_status",
    "share_view",
    "update_share_duration",
    "verify_attempt_failed",
]
