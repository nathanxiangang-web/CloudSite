"""shares 路由：公共分享与用户分享。"""
import time
from datetime import timezone

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from ..auth import require_user, validate_request_origin
from ..config import settings
from ..download import DownloadError, resolve_download_entry
from ..modules.providers.contracts.public import provider_runtime
from ..modules.resources.contracts.public import resource_queries
from ..modules.shares.contracts.public import (
    MAX_SHARE_DOWNLOADS,
    ShareNotFound,
    ShareValidationError,
    cancel_share as cancel_share_record,
    challenge_required,
    clear_verify_attempts,
    delete_share as delete_share_record,
    get_owned_share,
    get_share,
    list_owned_shares,
    record_share_access,
    reserve_share_download as reserve_share_download_record,
    reset_share_code as reset_share_code_record,
    restore_share as restore_share_record,
    share_payload,
    share_status as module_share_status,
    update_share_duration as update_share_duration_record,
    verify_attempt_failed,
)
from ..platform.observability import write_operation_log
from ..download_rate_limit import (
    check_download_rate,
    get_effective_client_ip,
    rate_limit_payload,
)
from ..request_context import request_is_https
from ..schemas import ShareInput, ShareUpdate, ShareVerifyInput
from ..services.shares import (
    build_share_target_payload,
    resolve_share_download_resource,
    share_dict,
    share_is_expired,
)
from ..shares.code import verify_share_code
from ..shares.service import (
    captcha_token_valid,
    create_share as create_share_row,
    ensure_share_active,
    target_valid_for_share,
)
from ..shares.ticket import create_share_ticket, share_cookie_name, validate_share_ticket
from ..modules.site.contracts.public import (
    share_page_image_name as get_share_page_image_name,
    share_page_settings_payload as get_share_page_settings_payload,
)
from ..site_assets import share_image_path

router = APIRouter()


def _translate_share_module_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ShareNotFound):
        return HTTPException(
            404,
            {"code": "SHARE_NOT_FOUND", "message": "分享不存在"},
        )
    if isinstance(exc, ShareValidationError):
        return HTTPException(
            exc.status_code,
            {"code": exc.code, "message": exc.message},
        )
    return HTTPException(
        500,
        {"code": "SHARE_ERROR", "message": "分享服务错误"},
    )


@router.get("/api/shares/{token}")
async def public_share(token: str):
    from ..main import StateSession, IndexSession

    async with StateSession() as state, IndexSession() as index:
        row = await get_share(state, token)
        if not row or not row.enabled or share_is_expired(row):
            raise HTTPException(410, "分享不存在、已关闭或已过期")
        if not await target_valid_for_share(state, index, row):
            raise HTTPException(
                404,
                {"code": "SHARE_TARGET_INVALID", "message": "分享目标已不可用"},
            )
        payload = await build_share_target_payload(state, index, row)
        row = await record_share_access(
            state,
            token,
            increment_view=False,
        )
        await state.commit()
        return {"share": share_payload(row), "target": payload}


@router.get("/api/public/share-page")
async def public_share_page_settings():
    from ..main import StateSession

    async with StateSession() as state:
        return await get_share_page_settings_payload(state)


@router.get("/api/public/share-page/image")
async def public_share_page_image():
    from ..main import StateSession

    async with StateSession() as state:
        image_name = await get_share_page_image_name(state)
        path = share_image_path(image_name)
    if not path:
        raise HTTPException(
            404,
            {"code": "SHARE_IMAGE_NOT_FOUND", "message": "分享页图片尚未配置"},
        )
    media_type = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".webp": "image/webp",
    }.get(path.suffix.lower())
    return FileResponse(
        path,
        media_type=media_type,
        headers={
            "Cache-Control": "no-cache",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/api/public/shares/{token}")
async def public_share_meta(token: str):
    from ..main import StateSession, IndexSession

    async with StateSession() as state, IndexSession() as index:
        row = await get_share(state, token)
        if not row:
            raise HTTPException(
                404,
                {"code": "SHARE_NOT_FOUND", "message": "分享不存在"},
            )
        target_valid = await target_valid_for_share(state, index, row)
        status = module_share_status(row, target_valid)
        if status == "active" and row.access_mode == "direct":
            return {
                "token": row.token,
                "status": "direct",
                "title": row.title or "CloudSite 资源分享",
                "access_mode": row.access_mode,
                "expires_at": row.expires_at,
                "download_count": row.download_count,
                "download_limit": MAX_SHARE_DOWNLOADS,
                "remaining_downloads": max(
                    MAX_SHARE_DOWNLOADS - row.download_count,
                    0,
                ),
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
async def public_share_verify(
    token: str,
    payload: ShareVerifyInput,
    request: Request,
    response: Response,
):
    from ..main import StateSession, IndexSession

    async with StateSession() as state, IndexSession() as index:
        row = await get_share(state, token)
        if not row:
            raise HTTPException(
                404,
                {"code": "SHARE_NOT_FOUND", "message": "分享不存在"},
            )
        ensure_share_active(
            row,
            module_share_status(
                row,
                await target_valid_for_share(state, index, row),
            ),
        )
        if row.access_mode != "code":
            raise HTTPException(
                400,
                {
                    "code": "SHARE_CODE_NOT_REQUIRED",
                    "message": "当前分享不需要分享码",
                },
            )
        address = get_effective_client_ip(request)
        if await challenge_required(
            state,
            token,
            address,
            secret_key=settings.secret_key,
        ):
            if not await captcha_token_valid(payload.captcha_token):
                raise HTTPException(
                    403,
                    {
                        "code": "SHARE_CAPTCHA_REQUIRED",
                        "message": "请先完成验证码验证",
                    },
                )
        if not verify_share_code(row.token, payload.code, row.code_hash):
            needs_captcha = await verify_attempt_failed(
                state,
                token,
                address,
                secret_key=settings.secret_key,
            )
            await state.commit()
            raise HTTPException(
                403,
                {
                    "code": "SHARE_CODE_INVALID",
                    "message": "分享码错误，请重新输入。",
                    "captcha_required": needs_captcha,
                },
            )
        await clear_verify_attempts(
            state,
            token,
            address,
            secret_key=settings.secret_key,
        )
        row = await record_share_access(
            state,
            token,
            increment_view=True,
        )
        await state.commit()
        expires_at = row.expires_at
        if expires_at and not expires_at.tzinfo:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        ticket = create_share_ticket(
            row.token,
            row.code_version,
            share_expires_at=(
                int(expires_at.timestamp())
                if expires_at
                else None
            ),
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
        row = await get_share(state, token)
        if not row:
            raise HTTPException(
                404,
                {"code": "SHARE_NOT_FOUND", "message": "分享不存在"},
            )
        ensure_share_active(
            row,
            module_share_status(
                row,
                await target_valid_for_share(state, index, row),
            ),
        )
        if row.access_mode == "code":
            cookie = request.cookies.get(share_cookie_name(row.token))
            if not validate_share_ticket(
                row.token,
                row.code_version,
                cookie,
            ):
                raise HTTPException(
                    401,
                    {
                        "code": "SHARE_TICKET_INVALID",
                        "message": "请先输入正确分享码",
                    },
                )
        elif row.access_mode == "direct":
            row = await record_share_access(
                state,
                token,
                increment_view=True,
            )
        payload = await build_share_target_payload(
            state,
            index,
            row,
        )
        await state.commit()
        return {"share": share_payload(row), "target": payload}


async def _share_download_response(
    token: str,
    request: Request,
    resource_id: str | None = None,
):
    from ..main import StateSession, IndexSession, _download_event

    started = time.perf_counter()
    async with StateSession() as state, IndexSession() as index:
        row = await get_share(state, token)
        if not row:
            raise HTTPException(
                404,
                {"code": "SHARE_NOT_FOUND", "message": "分享不存在"},
            )
        ensure_share_active(
            row,
            module_share_status(
                row,
                await target_valid_for_share(state, index, row),
            ),
        )
        if row.download_count >= MAX_SHARE_DOWNLOADS:
            raise HTTPException(
                410,
                {
                    "code": "SHARE_DOWNLOAD_LIMIT_REACHED",
                    "message": "分享下载次数已用完",
                },
            )
        if row.access_mode == "code":
            cookie = request.cookies.get(share_cookie_name(row.token))
            if not validate_share_ticket(
                row.token,
                row.code_version,
                cookie,
            ):
                raise HTTPException(
                    401,
                    {
                        "code": "SHARE_TICKET_INVALID",
                        "message": "请先输入正确分享码",
                    },
                )
        elif (
            row.access_mode == "direct"
            and row.object_type != "resource"
        ):
            raise HTTPException(
                400,
                {
                    "code": "SHARE_DIRECT_RESOURCE_ONLY",
                    "message": "无分享码直下只支持单文件",
                },
            )
        resource = await resolve_share_download_resource(
            state,
            index,
            row,
            resource_id,
        )
        rate = await check_download_rate(
            get_effective_client_ip(request)
        )
        if not rate.allowed:
            await _download_event(
                state,
                resource.id,
                "failed",
                "DOWNLOAD_RATE_LIMITED",
                started,
                source="share",
            )
            return JSONResponse(
                rate_limit_payload(rate),
                status_code=429,
                headers={"Retry-After": str(rate.retry_after)},
            )
        runtime = provider_runtime(state)
        try:
            resolution = await resolve_download_entry(
                resource,
                runtime,
            )
            try:
                await reserve_share_download_record(state, row.token)
            except ShareValidationError as exc:
                raise _translate_share_module_error(exc) from exc
            await _download_event(
                state,
                resource.id,
                "success",
                None,
                started,
                source="share",
            )
            return RedirectResponse(
                resolution.url,
                status_code=302,
            )
        except DownloadError as exc:
            await _download_event(
                state,
                resource.id,
                "failed",
                exc.code,
                started,
                source="share",
            )
            raise HTTPException(
                exc.status_code,
                {"code": exc.code, "message": exc.message},
            ) from exc


@router.get("/api/public/shares/{token}/download")
async def public_share_download(token: str, request: Request):
    return await _share_download_response(token, request)


@router.get("/api/public/shares/{token}/download/{resource_id}")
async def public_share_download_resource(token: str, resource_id: str, request: Request):
    return await _share_download_response(token, request, resource_id)


@router.get("/s/{token}")
async def short_share_direct_download(
    token: str,
    request: Request,
):
    from ..main import StateSession

    async with StateSession() as state:
        row = await get_share(state, token)
        if not row:
            raise HTTPException(
                404,
                {"code": "SHARE_NOT_FOUND", "message": "分享不存在"},
            )
        if row.access_mode != "direct":
            raise HTTPException(
                409,
                {
                    "code": "SHARE_CODE_REQUIRED",
                    "message": "请通过分享页面输入分享码",
                },
            )
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
        rows = await list_owned_shares(
            state,
            owner_user_id=user.id,
        )
        resource_ids = [
            row.object_id
            for row in rows
            if row.object_type == "resource"
        ]
        resources = await resource_queries(index).resource_references(
            resource_ids=resource_ids,
        )
        items = []
        for row in rows:
            status = module_share_status(
                row,
                await target_valid_for_share(state, index, row),
            )
            resource = resources.get(row.object_id)
            items.append(
                share_payload(row)
                | {
                    "expired": status == "expired",
                    "status": status,
                    "target_name": (
                        resource.name
                        if resource is not None
                        else None
                    ),
                }
            )
        await state.commit()
        return {"items": items}


@router.post("/api/my/shares")
async def create_my_share(
    payload: ShareInput,
    request: Request,
):
    from ..main import StateSession, IndexSession

    validate_request_origin(request)
    if payload.object_type != "resource":
        raise HTTPException(
            400,
            {
                "code": "USER_SHARE_RESOURCE_ONLY",
                "message": "普通用户目前只支持分享单个文件",
            },
        )
    async with StateSession() as state, IndexSession() as index:
        _, user = await require_user(state, request)
        created = await create_share_row(
            state,
            index,
            payload,
            creator_user_id=user.id,
        )
        await write_operation_log(
            state,
            module="share",
            action="user_share_created",
            message=(
                f"用户 {user.username} 创建分享 "
                f"{created.share.token}"
            ),
            actor_user_id=user.id,
        )
        await state.commit()
        return share_dict(created.share) | {"code": created.code}


@router.patch("/api/my/shares/{token}")
async def update_my_share(
    token: str,
    payload: ShareUpdate,
    request: Request,
):
    from ..main import StateSession

    validate_request_origin(request)
    async with StateSession() as state:
        _, user = await require_user(state, request)
        try:
            row = await get_owned_share(
                state,
                token,
                owner_user_id=user.id,
            )
            if payload.action == "cancel" or payload.enabled is False:
                row = await cancel_share_record(
                    state,
                    token,
                    owner_user_id=user.id,
                )
            elif payload.action == "restore" or payload.enabled is True:
                row = await restore_share_record(
                    state,
                    token,
                    duration=payload.duration,
                    owner_user_id=user.id,
                )
            elif payload.action == "reset_code":
                row, code = await reset_share_code_record(
                    state,
                    token,
                    secret_key=settings.secret_key,
                    owner_user_id=user.id,
                )
                await state.commit()
                return share_payload(row) | {"code": code}
            elif payload.action == "upgrade":
                raise HTTPException(
                    400,
                    {
                        "code": "SHARE_ACTION_NOT_ALLOWED",
                        "message": "当前操作不可用",
                    },
                )
            if (
                payload.duration
                and payload.action != "restore"
            ):
                row = await update_share_duration_record(
                    state,
                    token,
                    duration=payload.duration,
                    owner_user_id=user.id,
                )
            await state.commit()
            return share_payload(row)
        except (ShareNotFound, ShareValidationError) as exc:
            raise _translate_share_module_error(exc) from exc


@router.delete("/api/my/shares/{token}")
async def delete_my_share(token: str, request: Request):
    from ..main import StateSession

    validate_request_origin(request)
    async with StateSession() as state:
        _, user = await require_user(state, request)
        try:
            await delete_share_record(
                state,
                token,
                owner_user_id=user.id,
                action="user_share_deleted",
                message=f"用户 {user.username} 删除分享 {token}",
            )
            await state.commit()
            return {"ok": True}
        except ShareNotFound as exc:
            raise _translate_share_module_error(exc) from exc
