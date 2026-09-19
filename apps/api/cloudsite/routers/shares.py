"""shares 路由：公共分享与用户分享。"""
import time
from datetime import timezone

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from sqlalchemy import desc, select

from ..auth import require_user, validate_request_origin
from ..download import DownloadError, resolve_download_entry
from ..modules.providers.contracts.public import provider_runtime
from ..download_rate_limit import (
    check_download_rate,
    get_effective_client_ip,
    rate_limit_payload,
)
from ..models import Collection, Folder, OperationLog, Resource, Share, SiteSettings, utcnow
from ..request_context import request_is_https
from ..schemas import ShareInput, ShareUpdate, ShareVerifyInput
from ..services.collections import collection_dict
from ..services.resources import folder_dict, resource_dict
from ..services.shares import (
    build_share_target_payload,
    owned_share,
    resolve_share_download_resource,
    share_dict,
    share_is_expired,
)
from ..shares.code import verify_share_code
from ..shares.service import (
    MAX_SHARE_DOWNLOADS,
    cancel_share as cancel_share_row,
    captcha_token_valid,
    challenge_required,
    clear_verify_attempts,
    create_share as create_share_row,
    ensure_share_active,
    reserve_share_download,
    reset_share_code,
    restore_share,
    share_status,
    target_valid_for_share,
    update_share_duration,
)
from ..shares.ticket import create_share_ticket, share_cookie_name, validate_share_ticket
from ..site_assets import share_image_path

router = APIRouter()


@router.get("/api/shares/{token}")
async def public_share(token: str):
    from ..main import StateSession, IndexSession

    async with StateSession() as state, IndexSession() as index:
        row = await state.get(Share, token)
        if not row or not row.enabled or share_is_expired(row):
            raise HTTPException(410, "分享不存在、已关闭或已过期")
        if not await target_valid_for_share(state, index, row):
            raise HTTPException(404, {"code": "SHARE_TARGET_INVALID", "message": "分享目标已不可用"})
        if row.object_type == "resource":
            target = await index.get(Resource, row.object_id)
            payload = resource_dict(target)
        elif row.object_type == "folder":
            target = await index.get(Folder, row.object_id)
            child_folders = list((await index.scalars(select(Folder).where(Folder.parent_id == target.id, Folder.status == "active", Folder.root_mapping_id == target.root_mapping_id).order_by(Folder.name))).all())
            child_resources = list((await index.scalars(select(Resource).where(Resource.parent_id == target.id, Resource.status == "active", Resource.root_mapping_id == target.root_mapping_id).order_by(Resource.name))).all())
            payload = {"folder": folder_dict(target), "folders": [folder_dict(item) for item in child_folders], "resources": [resource_dict(item) for item in child_resources]}
        else:
            target = await state.get(Collection, int(row.object_id)) if row.object_id.isdigit() else None
            payload = await collection_dict(state, index, target, include_items=True)
        row.access_count += 1
        row.last_accessed_at = utcnow()
        await state.commit()
        return {"share": share_dict(row), "target": payload}


@router.get("/api/public/share-page")
async def public_share_page_settings():
    from ..main import StateSession

    async with StateSession() as state:
        row = await state.get(SiteSettings, 1) or SiteSettings(id=1)
        return {
            "site_name": row.site_name or "CloudSite",
            "share_image_url": "/api/public/share-page/image" if row.share_image_name else "",
        }


@router.get("/api/public/share-page/image")
async def public_share_page_image():
    from ..main import StateSession

    async with StateSession() as state:
        row = await state.get(SiteSettings, 1)
        path = share_image_path(row.share_image_name) if row else None
    if not path:
        raise HTTPException(404, {"code": "SHARE_IMAGE_NOT_FOUND", "message": "分享页图片尚未配置"})
    media_type = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}.get(path.suffix.lower())
    return FileResponse(
        path,
        media_type=media_type,
        headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/api/public/shares/{token}")
async def public_share_meta(token: str):
    from ..main import StateSession, IndexSession

    async with StateSession() as state, IndexSession() as index:
        row = await state.get(Share, token)
        if not row:
            raise HTTPException(404, {"code": "SHARE_NOT_FOUND", "message": "分享不存在"})
        target_valid = await target_valid_for_share(state, index, row)
        status = share_status(row, target_valid)
        if status == "active" and row.access_mode == "direct":
            return {
                "token": row.token,
                "status": "direct",
                "title": row.title or "CloudSite 资源分享",
                "access_mode": row.access_mode,
                "expires_at": row.expires_at,
                "download_count": row.download_count,
                "download_limit": MAX_SHARE_DOWNLOADS,
                "remaining_downloads": max(MAX_SHARE_DOWNLOADS - (row.download_count or 0), 0),
            }
        if status == "active":
            return {
                "token": row.token,
                "status": "code_required",
                "title": row.title or "CloudSite 资源分享",
                "access_mode": row.access_mode,
                "expires_at": row.expires_at,
            }
        return {
            "token": row.token,
            "status": status,
            "title": row.title or "CloudSite 资源分享",
            "access_mode": row.access_mode,
            "expires_at": row.expires_at,
            "cancel_reason": row.cancel_reason,
        }


@router.post("/api/public/shares/{token}/verify")
async def public_share_verify(token: str, payload: ShareVerifyInput, request: Request, response: Response):
    from ..main import StateSession, IndexSession

    async with StateSession() as state, IndexSession() as index:
        row = await state.get(Share, token)
        if not row:
            raise HTTPException(404, {"code": "SHARE_NOT_FOUND", "message": "分享不存在"})
        ensure_share_active(row, share_status(row, await target_valid_for_share(state, index, row)))
        if row.access_mode != "code":
            raise HTTPException(400, {"code": "SHARE_CODE_NOT_REQUIRED", "message": "当前分享不需要分享码"})
        address = get_effective_client_ip(request)
        if await challenge_required(state, token, address):
            if not await captcha_token_valid(payload.captcha_token):
                raise HTTPException(403, {"code": "SHARE_CAPTCHA_REQUIRED", "message": "请先完成验证码验证"})
        if not verify_share_code(row.token, payload.code, row.code_hash):
            needs_captcha = await verify_attempt_failed(state, token, address)
            await state.commit()
            raise HTTPException(
                403,
                {
                    "code": "SHARE_CODE_INVALID",
                    "message": "分享码错误，请重新输入。",
                    "captcha_required": needs_captcha,
                },
            )
        await clear_verify_attempts(state, token, address)
        row.view_count += 1
        row.access_count = row.view_count
        row.last_accessed_at = utcnow()
        await state.commit()
        expires_at = row.expires_at
        if expires_at and not expires_at.tzinfo:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        ticket = create_share_ticket(
            row.token,
            row.code_version,
            share_expires_at=int(expires_at.timestamp()) if expires_at else None,
        )
        response.set_cookie(
            share_cookie_name(row.token),
            ticket,
            max_age=3600,
            httponly=True,
            secure=request_is_https(request),
            samesite="lax",
            path=f"/s/{row.token}",
        )
        return {"ok": True, "ticket_expires_in": 3600}


@router.get("/api/public/shares/{token}/content")
async def public_share_content(token: str, request: Request):
    from ..main import StateSession, IndexSession

    async with StateSession() as state, IndexSession() as index:
        row = await state.get(Share, token)
        if not row:
            raise HTTPException(404, {"code": "SHARE_NOT_FOUND", "message": "分享不存在"})
        ensure_share_active(row, share_status(row, await target_valid_for_share(state, index, row)))
        if row.access_mode == "code":
            cookie = request.cookies.get(share_cookie_name(row.token))
            if not validate_share_ticket(row.token, row.code_version, cookie):
                raise HTTPException(401, {"code": "SHARE_TICKET_INVALID", "message": "请先输入正确分享码"})
        elif row.access_mode == "direct":
            row.view_count += 1
            row.access_count = row.view_count
            row.last_accessed_at = utcnow()
        payload = await build_share_target_payload(state, index, row)
        await state.commit()
        return {"share": share_dict(row), "target": payload}


async def _share_download_response(token: str, request: Request, resource_id: str | None = None):
    from ..main import StateSession, IndexSession, _download_event

    started = time.perf_counter()
    async with StateSession() as state, IndexSession() as index:
        row = await state.get(Share, token)
        if not row:
            raise HTTPException(404, {"code": "SHARE_NOT_FOUND", "message": "分享不存在"})
        ensure_share_active(row, share_status(row, await target_valid_for_share(state, index, row)))
        if (row.download_count or 0) >= MAX_SHARE_DOWNLOADS:
            raise HTTPException(410, {"code": "SHARE_DOWNLOAD_LIMIT_REACHED", "message": "分享下载次数已用完"})
        if row.access_mode == "code":
            cookie = request.cookies.get(share_cookie_name(row.token))
            if not validate_share_ticket(row.token, row.code_version, cookie):
                raise HTTPException(401, {"code": "SHARE_TICKET_INVALID", "message": "请先输入正确分享码"})
        elif row.access_mode == "direct" and row.object_type != "resource":
            raise HTTPException(400, {"code": "SHARE_DIRECT_RESOURCE_ONLY", "message": "无分享码直下只支持单文件"})
        resource = await resolve_share_download_resource(state, index, row, resource_id)
        rate = await check_download_rate(get_effective_client_ip(request))
        if not rate.allowed:
            await _download_event(state, resource.id, "failed", "DOWNLOAD_RATE_LIMITED", started, source="share")
            return JSONResponse(rate_limit_payload(rate), status_code=429, headers={"Retry-After": str(rate.retry_after)})
        runtime = provider_runtime(state)
        try:
            resolution = await resolve_download_entry(resource, runtime)
            await reserve_share_download(state, row.token)
            await _download_event(state, resource.id, "success", None, started, source="share")
            return RedirectResponse(resolution.url, status_code=302)
        except DownloadError as exc:
            await _download_event(state, resource.id, "failed", exc.code, started, source="share")
            raise HTTPException(exc.status_code, {"code": exc.code, "message": exc.message}) from exc


@router.get("/api/public/shares/{token}/download")
async def public_share_download(token: str, request: Request):
    return await _share_download_response(token, request)


@router.get("/api/public/shares/{token}/download/{resource_id}")
async def public_share_download_resource(token: str, resource_id: str, request: Request):
    return await _share_download_response(token, request, resource_id)


@router.get("/s/{token}")
async def short_share_direct_download(token: str, request: Request):
    from ..main import StateSession

    async with StateSession() as state:
        row = await state.get(Share, token)
        if not row:
            raise HTTPException(404, {"code": "SHARE_NOT_FOUND", "message": "分享不存在"})
        if row.access_mode != "direct":
            raise HTTPException(409, {"code": "SHARE_CODE_REQUIRED", "message": "请通过分享页面输入分享码"})
    return await _share_download_response(token, request)


@router.get("/s/{token}/d")
async def short_share_download(token: str, request: Request):
    return await _share_download_response(token, request)


@router.get("/s/{token}/d/{resource_id}")
async def short_share_download_resource(token: str, resource_id: str, request: Request):
    return await _share_download_response(token, request, resource_id)


@router.get("/api/my/shares")
async def my_shares(request: Request):
    from ..main import StateSession, IndexSession

    async with StateSession() as state, IndexSession() as index:
        _, user = await require_user(state, request)
        rows = list(
            (
                await state.scalars(
                    select(Share)
                    .where(Share.creator_user_id == user.id)
                    .order_by(desc(Share.created_at))
                )
            ).all()
        )
        resource_ids = [row.object_id for row in rows if row.object_type == "resource"]
        names = {
            item.id: item.name
            for item in (
                await index.scalars(select(Resource).where(Resource.id.in_(resource_ids)))
            ).all()
        } if resource_ids else {}
        items = []
        for row in rows:
            status = share_status(row, await target_valid_for_share(state, index, row))
            items.append(
                share_dict(row)
                | {
                    "expired": status == "expired",
                    "status": status,
                    "target_name": names.get(row.object_id),
                }
            )
        await state.commit()
        return {"items": items}


@router.post("/api/my/shares")
async def create_my_share(payload: ShareInput, request: Request):
    from ..main import StateSession, IndexSession

    validate_request_origin(request)
    if payload.object_type != "resource":
        raise HTTPException(
            400,
            {"code": "USER_SHARE_RESOURCE_ONLY", "message": "普通用户目前只支持分享单个文件"},
        )
    async with StateSession() as state, IndexSession() as index:
        _, user = await require_user(state, request)
        created = await create_share_row(
            state,
            index,
            payload,
            creator_user_id=user.id,
        )
        state.add(
            OperationLog(
                level="INFO",
                module="share",
                action="user_share_created",
                message=f"用户 {user.username} 创建分享 {created.share.token}",
            )
        )
        await state.commit()
        return share_dict(created.share) | {"code": created.code}


@router.patch("/api/my/shares/{token}")
async def update_my_share(token: str, payload: ShareUpdate, request: Request):
    from ..main import StateSession

    validate_request_origin(request)
    async with StateSession() as state:
        _, user = await require_user(state, request)
        row = await owned_share(state, token, user.id)
        if payload.action == "cancel" or payload.enabled is False:
            await cancel_share_row(state, row)
        elif payload.action == "restore" or payload.enabled is True:
            await restore_share(state, row, payload.duration)
        elif payload.action == "reset_code":
            code = await reset_share_code(state, row)
            await state.commit()
            return share_dict(row) | {"code": code}
        elif payload.action == "upgrade":
            raise HTTPException(400, {"code": "SHARE_ACTION_NOT_ALLOWED", "message": "当前操作不可用"})
        if payload.duration and payload.action != "restore":
            await update_share_duration(state, row, payload.duration)
        await state.commit()
        return share_dict(row)


@router.delete("/api/my/shares/{token}")
async def delete_my_share(token: str, request: Request):
    from ..main import StateSession

    validate_request_origin(request)
    async with StateSession() as state:
        _, user = await require_user(state, request)
        row = await owned_share(state, token, user.id)
        state.add(
            OperationLog(
                level="INFO",
                module="share",
                action="user_share_deleted",
                message=f"用户 {user.username} 删除分享 {token}",
            )
        )
        await state.delete(row)
        await state.commit()
        return {"ok": True}
