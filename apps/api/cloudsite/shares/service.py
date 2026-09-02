from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import HTTPException
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from cloudsite.config import settings
from cloudsite.models import Collection, CollectionItem, ContentRootMapping, Folder, OperationLog, Resource, Share, ShareVerifyAttempt, utcnow

from .code import generate_share_code, hash_share_code, verify_share_code


MAX_SHARE_DOWNLOADS = 404
SHARE_TOKEN_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
DURATION_OPTIONS = {"5m", "1h", "6h", "24h", "7d", "permanent"}
ShareStatus = Literal["active", "cancelled", "expired", "invalid_target", "migration_pending"]


@dataclass(slots=True)
class CreatedShare:
    share: Share
    code: str | None


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
    return set((await session.scalars(select(ContentRootMapping.id).where(ContentRootMapping.enabled.is_(True)))).all())


async def resource_in_publication_scope(state: AsyncSession, resource: Resource | None) -> bool:
    if not resource or resource.status != "active" or resource.root_mapping_id is None:
        return False
    return resource.root_mapping_id in await enabled_root_ids(state)


async def folder_in_publication_scope(state: AsyncSession, index: AsyncSession, folder: Folder | None) -> bool:
    if not folder or folder.status != "active" or folder.root_mapping_id is None:
        return False
    roots = await enabled_root_ids(state)
    if folder.root_mapping_id not in roots:
        return False
    leaked = await index.scalar(
        select(Resource.id)
        .where(Resource.parent_id == folder.id, Resource.status == "active")
        .where((Resource.root_mapping_id.is_(None)) | (Resource.root_mapping_id.not_in(roots)))
        .limit(1)
    )
    return leaked is None


async def collection_in_publication_scope(state: AsyncSession, index: AsyncSession, collection: Collection | None) -> bool:
    if not collection or collection.status != "active":
        return False
    ids = list((await state.scalars(select(CollectionItem.resource_id).where(CollectionItem.collection_id == collection.id))).all())
    if not ids:
        return True
    roots = await enabled_root_ids(state)
    active_count = await index.scalar(
        select(func.count())
        .select_from(Resource)
        .where(Resource.id.in_(ids), Resource.status == "active", Resource.root_mapping_id.is_not(None))
        .where(Resource.root_mapping_id.in_(roots))
    )
    return int(active_count or 0) == len(set(ids))


async def target_valid_for_share(state: AsyncSession, index: AsyncSession, share: Share) -> bool:
    if share.object_type == "resource":
        return await resource_in_publication_scope(state, await index.get(Resource, share.object_id))
    if share.object_type == "folder":
        return await folder_in_publication_scope(state, index, await index.get(Folder, share.object_id))
    collection = await state.get(Collection, int(share.object_id)) if share.object_id.isdigit() else None
    return await collection_in_publication_scope(state, index, collection)


async def create_share(state: AsyncSession, index: AsyncSession, payload) -> CreatedShare:
    if payload.access_mode == "direct" and payload.object_type != "resource":
        raise HTTPException(400, {"code": "SHARE_DIRECT_RESOURCE_ONLY", "message": "无分享码直下只支持单文件"})
    if payload.object_type == "resource":
        target = await index.get(Resource, payload.object_id)
        valid = await resource_in_publication_scope(state, target)
    elif payload.object_type == "folder":
        target = await index.get(Folder, payload.object_id)
        valid = await folder_in_publication_scope(state, index, target)
    else:
        target = await state.get(Collection, int(payload.object_id)) if payload.object_id.isdigit() else None
        valid = await collection_in_publication_scope(state, index, target)
    if not target or not valid:
        raise HTTPException(400, {"code": "SHARE_TARGET_INVALID", "message": "分享对象不存在或不在发布范围内"})
    token = generate_share_token()
    while await state.get(Share, token):
        token = generate_share_token()
    code = generate_share_code() if payload.access_mode == "code" else None
    row = Share(
        token=token,
        object_type=payload.object_type,
        object_id=payload.object_id,
        title=payload.title,
        enabled=True,
        access_mode=payload.access_mode,
        code_hash=hash_share_code(token, code) if code else None,
        code_version=1 if code else 0,
        expires_at=share_expires_at(payload.duration),
        access_count=0,
        view_count=0,
        download_count=0,
    )
    state.add(row)
    await log_share_operation(state, "share_created", f"创建分享 {token}")
    return CreatedShare(row, code)


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


async def verify_attempt_failed(session: AsyncSession, share_token: str, address: str) -> bool:
    key = ip_hash(address)
    now = utcnow()
    window_started = now - timedelta(minutes=10)
    row = await session.scalar(
        select(ShareVerifyAttempt).where(ShareVerifyAttempt.share_token == share_token, ShareVerifyAttempt.ip_hash == key)
    )
    if not row or aware_utc(row.window_started_at) <= window_started:
        row = ShareVerifyAttempt(share_token=share_token, ip_hash=key, fail_count=1, window_started_at=now, updated_at=now)
        session.add(row)
        return False
    row.fail_count += 1
    row.updated_at = now
    if row.fail_count >= 5:
        row.challenge_required_until = now + timedelta(minutes=10)
        return True
    return False


async def challenge_required(session: AsyncSession, share_token: str, address: str) -> bool:
    row = await session.scalar(
        select(ShareVerifyAttempt).where(ShareVerifyAttempt.share_token == share_token, ShareVerifyAttempt.ip_hash == ip_hash(address))
    )
    return bool(row and row.challenge_required_until and aware_utc(row.challenge_required_until) > utcnow())


async def clear_verify_attempts(session: AsyncSession, share_token: str, address: str) -> None:
    await session.execute(
        delete(ShareVerifyAttempt).where(
            ShareVerifyAttempt.share_token == share_token,
            ShareVerifyAttempt.ip_hash == ip_hash(address),
        )
    )


async def cleanup_share_verify_attempts(now: datetime | None = None) -> int:
    current = now or utcnow()
    threshold = current - timedelta(hours=1)
    from cloudsite.database import StateSession

    async with StateSession() as session:
        result = await session.execute(delete(ShareVerifyAttempt).where(ShareVerifyAttempt.updated_at < threshold))
        await session.commit()
        return int(result.rowcount or 0)


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
