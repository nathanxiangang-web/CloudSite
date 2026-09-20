from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from cloudsite.config import settings
from cloudsite.modules.collections.contracts.public import (
    collection_publication_scope as _collection_publication_scope,
)
from cloudsite.modules.providers.contracts.public import (
    enabled_root_ids as _enabled_root_ids,
)
from cloudsite.modules.resources.contracts.public import (
    folder_publication_target as _folder_publication_target,
)
from cloudsite.modules.shares.contracts.public import (
    CreatedShareView as CreatedShare,
    challenge_required as _module_challenge_required,
    cleanup_share_verify_attempts as _module_cleanup_share_verify_attempts,
    clear_verify_attempts as _module_clear_verify_attempts,
    create_share as _module_create_share,
    target_valid_for_share as _module_target_valid_for_share,
    verify_attempt_failed as _module_verify_attempt_failed,
)
from cloudsite.models import OperationLog, Share, utcnow

from .code import generate_share_code, hash_share_code, verify_share_code


MAX_SHARE_DOWNLOADS = 404
SHARE_TOKEN_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
DURATION_OPTIONS = {"5m", "1h", "6h", "24h", "7d", "permanent"}
ShareStatus = Literal["active", "cancelled", "expired", "invalid_target", "migration_pending"]


def aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def share_expires_at(duration: str, now: datetime | None = None) -> datetime | None:
    if duration not in DURATION_OPTIONS:
        raise HTTPException(400, {"code": "SHARE_DURATION_INVALID", "message": "有效期选项无效"})
    current = now or utcnow()
    return {
        "5m": current + timedelta(minutes=5),
        "1h": current + timedelta(hours=1),
        "6h": current + timedelta(hours=6),
        "24h": current + timedelta(hours=24),
        "7d": current + timedelta(days=7),
        "permanent": None,
    }[duration]


def generate_share_token(length: int = 12) -> str:
    return "".join(secrets.choice(SHARE_TOKEN_ALPHABET) for _ in range(length))


def share_status(share: Share, target_valid: bool = True, now: datetime | None = None) -> ShareStatus:
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


def public_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code, {"code": code, "message": message})


def ensure_share_active(share: Share, status: ShareStatus | None = None) -> None:
    current_status = status or share_status(share)
    if current_status == "active":
        return
    mapping = {
        "migration_pending": (409, "SHARE_MIGRATION_REQUIRED", "分享需要管理员升级后才能匿名访问"),
        "cancelled": (410, "SHARE_CANCELLED", "分享已取消"),
        "expired": (410, "SHARE_EXPIRED", "分享已过期"),
        "invalid_target": (404, "SHARE_TARGET_INVALID", "分享目标已不可用"),
    }
    status_code, code, message = mapping[current_status]
    raise public_error(status_code, code, message)


async def log_share_operation(session: AsyncSession, action: str, message: str, level: str = "INFO") -> None:
    session.add(OperationLog(level=level, module="share", action=action, message=message))


async def enabled_root_ids(session: AsyncSession) -> set[int]:
    return await _enabled_root_ids(session)


async def resource_in_publication_scope(
    state: AsyncSession,
    resource,
) -> bool:
    if (
        resource is None
        or resource.status != "active"
        or resource.root_mapping_id is None
    ):
        return False
    return resource.root_mapping_id in await _enabled_root_ids(state)


async def folder_in_publication_scope(
    state: AsyncSession,
    index: AsyncSession,
    folder,
) -> bool:
    if folder is None:
        return False
    return (
        await _folder_publication_target(
            state,
            index,
            folder.id,
        )
        is not None
    )


async def collection_in_publication_scope(
    state: AsyncSession,
    index: AsyncSession,
    collection,
) -> bool:
    if collection is None:
        return False
    return await _collection_publication_scope(
        state,
        index,
        collection.id,
    )


async def target_valid_for_share(
    state: AsyncSession,
    index: AsyncSession,
    share,
) -> bool:
    return await _module_target_valid_for_share(
        state,
        index,
        share,
    )


async def create_share(
    state: AsyncSession,
    index: AsyncSession,
    payload,
    *,
    creator_user_id: int | None = None,
) -> CreatedShare:
    try:
        return await _module_create_share(
            state,
            index,
            object_type=payload.object_type,
            object_id=payload.object_id,
            access_mode=payload.access_mode,
            duration=payload.duration,
            title=payload.title,
            secret_key=settings.secret_key,
            creator_user_id=creator_user_id,
        )
    except Exception as exc:
        from cloudsite.modules.shares.contracts.public import ShareValidationError

        if isinstance(exc, ShareValidationError):
            raise HTTPException(
                exc.status_code,
                {"code": exc.code, "message": exc.message},
            ) from exc
        raise


async def reset_share_code(session: AsyncSession, share: Share) -> str:
    if share.access_mode != "code":
        raise HTTPException(400, {"code": "SHARE_DIRECT_HAS_NO_CODE", "message": "直下分享没有分享码"})
    code = generate_share_code()
    share.code_hash = hash_share_code(share.token, code)
    share.code_version = max(share.code_version or 0, 0) + 1
    share.enabled = True
    share.cancelled_at = None
    share.cancel_reason = None
    share.updated_at = utcnow()
    await log_share_operation(session, "share_code_reset", f"重置分享码 {share.token}")
    return code


async def cancel_share(session: AsyncSession, share: Share, reason: str = "manual") -> None:
    share.enabled = False
    share.cancelled_at = utcnow()
    share.cancel_reason = reason
    share.updated_at = share.cancelled_at
    await log_share_operation(session, "share_cancelled", f"取消分享 {share.token}")


async def restore_share(session: AsyncSession, share: Share, duration: str | None = None) -> None:
    if share.download_count >= MAX_SHARE_DOWNLOADS:
        raise HTTPException(400, {"code": "SHARE_DOWNLOAD_LIMIT_REACHED", "message": "已达到下载上限，不能恢复"})
    expires_at = aware_utc(share.expires_at)
    if expires_at and expires_at <= utcnow():
        if not duration:
            raise HTTPException(400, {"code": "SHARE_DURATION_REQUIRED", "message": "过期分享恢复时需要重新选择有效期"})
        share.expires_at = share_expires_at(duration)
    share.enabled = True
    share.cancelled_at = None
    share.cancel_reason = None
    share.updated_at = utcnow()
    await log_share_operation(session, "share_restored", f"恢复分享 {share.token}")


async def update_share_duration(session: AsyncSession, share: Share, duration: str) -> None:
    share.expires_at = share_expires_at(duration)
    share.updated_at = utcnow()
    await log_share_operation(session, "share_updated", f"修改分享有效期 {share.token}")


async def reserve_share_download(session: AsyncSession, token: str) -> int:
    now = utcnow()
    result = await session.execute(
        text(
            "UPDATE shares "
            "SET download_count = download_count + 1, "
            "last_downloaded_at = :now, "
            "enabled = CASE WHEN download_count + 1 >= :max_downloads THEN 0 ELSE enabled END, "
            "cancelled_at = CASE WHEN download_count + 1 >= :max_downloads THEN :now ELSE cancelled_at END, "
            "cancel_reason = CASE WHEN download_count + 1 >= :max_downloads THEN 'download_limit' ELSE cancel_reason END, "
            "updated_at = :now "
            "WHERE token = :token AND enabled = 1 AND download_count < :max_downloads"
        ),
        {"token": token, "now": now, "max_downloads": MAX_SHARE_DOWNLOADS},
    )
    if result.rowcount != 1:
        raise public_error(410, "SHARE_DOWNLOAD_LIMIT_REACHED", "分享下载次数已用完")
    count = await session.scalar(select(Share.download_count).where(Share.token == token))
    if int(count or 0) == MAX_SHARE_DOWNLOADS:
        await log_share_operation(session, "share_download_limit_reached", f"分享 {token} 达到下载上限")
    return int(count or 0)


def ip_hash(address: str) -> str:
    return hmac.new(settings.secret_key.encode(), f"share-ip:{address}".encode(), hashlib.sha256).hexdigest()


async def verify_attempt_failed(
    session: AsyncSession,
    share_token: str,
    address: str,
) -> bool:
    return await _module_verify_attempt_failed(
        session,
        share_token,
        address,
        secret_key=settings.secret_key,
    )


async def challenge_required(
    session: AsyncSession,
    share_token: str,
    address: str,
) -> bool:
    return await _module_challenge_required(
        session,
        share_token,
        address,
        secret_key=settings.secret_key,
    )


async def clear_verify_attempts(
    session: AsyncSession,
    share_token: str,
    address: str,
) -> None:
    await _module_clear_verify_attempts(
        session,
        share_token,
        address,
        secret_key=settings.secret_key,
    )


async def cleanup_share_verify_attempts(
    now: datetime | None = None,
) -> int:
    return await _module_cleanup_share_verify_attempts(now)


async def cleanup_terminal_shares(now: datetime | None = None) -> int:
    current = now or utcnow()
    cutoff = current - timedelta(hours=48)
    from cloudsite.database import StateSession

    async with StateSession() as session:
        rows = list(
            (
                await session.scalars(
                    select(Share).where(
                        ((Share.expires_at.is_not(None)) & (Share.expires_at <= cutoff))
                        | ((Share.cancelled_at.is_not(None)) & (Share.cancelled_at <= cutoff))
                    )
                )
            ).all()
        )
        for row in rows:
            action = "share_expired_cleanup" if row.expires_at and aware_utc(row.expires_at) <= cutoff else "share_cancelled_cleanup"
            await log_share_operation(session, action, f"自动清理分享 {row.token}")
            await session.delete(row)
        await session.commit()
        return len(rows)


async def captcha_token_valid(token: str | None) -> bool:
    # The data model keeps the challenge state without Redis. Third-party
    # Turnstile verification can be wired here when a site key/secret is added.
    return bool(token)
