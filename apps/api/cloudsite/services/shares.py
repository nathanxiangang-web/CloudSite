"""shares 服务：分享序列化与下载资源解析辅助函数。"""
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select

from ..models import Collection, CollectionItem, Folder, Resource, Share
from ..shares.service import (
    MAX_SHARE_DOWNLOADS,
    resource_in_publication_scope,
    target_valid_for_share,
)
from .collections import collection_dict
from .resources import folder_dict, resource_dict


def share_dict(row: Share) -> dict:
    view_count = row.view_count if row.view_count is not None else row.access_count
    return {
        "token": row.token,
        "object_type": row.object_type,
        "object_id": row.object_id,
        "title": row.title,
        "enabled": row.enabled,
        "access_mode": row.access_mode,
        "has_code": bool(row.code_hash),
        "code_version": row.code_version,
        "expires_at": row.expires_at,
        "cancelled_at": row.cancelled_at,
        "cancel_reason": row.cancel_reason,
        "access_count": row.access_count,
        "view_count": view_count,
        "download_count": row.download_count,
        "download_limit": MAX_SHARE_DOWNLOADS,
        "remaining_downloads": max(MAX_SHARE_DOWNLOADS - (row.download_count or 0), 0),
        "last_accessed_at": row.last_accessed_at,
        "last_downloaded_at": row.last_downloaded_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def share_is_expired(row: Share) -> bool:
    if not row.expires_at:
        return False
    expires_at = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= datetime.now(timezone.utc)


async def build_share_target_payload(state, index, row: Share) -> dict:
    if row.object_type == "resource":
        target = await index.get(Resource, row.object_id)
        if not target or not await target_valid_for_share(state, index, row):
            raise HTTPException(404, {"code": "SHARE_TARGET_INVALID", "message": "分享的资源不存在或不可用"})
        return resource_dict(target)
    if row.object_type == "folder":
        target = await index.get(Folder, row.object_id)
        if not target or not await target_valid_for_share(state, index, row):
            raise HTTPException(404, {"code": "SHARE_TARGET_INVALID", "message": "分享的文件夹不存在或不可用"})
        child_folders = list((await index.scalars(select(Folder).where(Folder.parent_id == target.id, Folder.status == "active", Folder.root_mapping_id == target.root_mapping_id).order_by(Folder.name))).all())
        child_resources = list((await index.scalars(select(Resource).where(Resource.parent_id == target.id, Resource.status == "active", Resource.root_mapping_id == target.root_mapping_id).order_by(Resource.name))).all())
        return {"folder": folder_dict(target), "folders": [folder_dict(item) for item in child_folders], "resources": [resource_dict(item) for item in child_resources]}
    target = await state.get(Collection, int(row.object_id)) if row.object_id.isdigit() else None
    if not target or not await target_valid_for_share(state, index, row):
        raise HTTPException(404, {"code": "SHARE_TARGET_INVALID", "message": "分享的合集不存在或不可用"})
    return await collection_dict(state, index, target, include_items=True)


async def resolve_share_download_resource(state, index, row: Share, resource_id: str | None):
    if row.object_type == "resource":
        selected_id = resource_id or row.object_id
        if selected_id != row.object_id:
            raise HTTPException(403, {"code": "SHARE_RESOURCE_NOT_ALLOWED", "message": "资源不属于当前分享"})
        resource = await index.get(Resource, row.object_id)
    elif row.object_type == "folder":
        if not resource_id:
            raise HTTPException(400, {"code": "SHARE_RESOURCE_REQUIRED", "message": "请选择要下载的资源"})
        resource = await index.get(Resource, resource_id)
        if not resource or resource.parent_id != row.object_id:
            raise HTTPException(403, {"code": "SHARE_RESOURCE_NOT_ALLOWED", "message": "资源不属于当前分享"})
    else:
        if not resource_id:
            raise HTTPException(400, {"code": "SHARE_RESOURCE_REQUIRED", "message": "请选择要下载的资源"})
        collection_id = int(row.object_id) if row.object_id.isdigit() else -1
        allowed = await state.scalar(
            select(CollectionItem.id).where(CollectionItem.collection_id == collection_id, CollectionItem.resource_id == resource_id)
        )
        if not allowed:
            raise HTTPException(403, {"code": "SHARE_RESOURCE_NOT_ALLOWED", "message": "资源不属于当前分享"})
        resource = await index.get(Resource, resource_id)
    if not await resource_in_publication_scope(state, resource):
        raise HTTPException(404, {"code": "SHARE_TARGET_INVALID", "message": "分享资源已不可用"})
    return resource


async def owned_share(state, token: str, user_id: int) -> Share:
    row = await state.scalar(
        select(Share).where(Share.token == token, Share.creator_user_id == user_id)
    )
    if not row:
        raise HTTPException(404, {"code": "SHARE_NOT_FOUND", "message": "分享不存在"})
    return row