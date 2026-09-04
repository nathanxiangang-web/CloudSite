import asyncio
import base64
import hashlib
import hmac
import json
import logging
import math
import random
import time
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from urllib.parse import urlencode

from fastapi import FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy import delete, desc, func, select, text

from . import __version__
from .alist import AListClient, AListError
from .auth import require_user, router as auth_router, validate_request_origin
from .config import settings
from .crypto import decrypt_secret, encrypt_secret
from .database import IndexSession, StateSession, init_databases, validate_database_files
from .download import DownloadError, resolve_download_entry, validate_download_url, validate_resource_id
from .download_rate_limit import (
    DOWNLOAD_RATE_CLEANUP_SECONDS,
    check_download_rate,
    cleanup_download_rate_limits,
    get_effective_client_ip,
    rate_limit_payload,
)
from .identity import backup_stable_id_databases, migrate_stable_resource_ids
from .indexer import (
    automatic_sync_due,
    log_operation,
    normalize_path,
    recover_interrupted_sync_runs,
    run_sync,
    sync_circuit_status,
    sync_preflight,
)
from .models import (
    AListConnection,
    Collection,
    CollectionItem,
    ContentRootMapping,
    DownloadEvent,
    DownloadDiagnostic,
    Folder,
    OperationLog,
    Resource,
    ResourceIdentity,
    ResourceIdentityCandidate,
    ResourceIdentityHistory,
    Share,
    SiteSettings,
    SyncRun,
    SystemSetting,
    User,
    utcnow,
)
from .office import OfficePreviewError, ensure_preview_cached, office_cache_filename, office_content_type
from .preview import PreviewError, load_text_preview, preview_capability, resolve_preview_url, validate_preview_ticket
from .providers.service import provider_info
from .request_context import request_is_https
from .schemas import (
    AListInput,
    AdminLoginInput,
    ContentRootListOutput,
    CollectionInput,
    CollectionItemsInput,
    DownloadDiagnosticInput,
    RootMappingInput,
    FolderDetailOutput,
    FolderListOutput,
    ResourceDetailOutput,
    ResourcePageOutput,
    SearchOutput,
    ShareInput,
    ShareUpdate,
    ShareVerifyInput,
    SiteSettingsUpdate,
    SyncInput,
    SystemInput,
    TextPreviewOutput,
)
from .shares.code import verify_share_code
from .shares.service import (
    MAX_SHARE_DOWNLOADS,
    cancel_share as cancel_share_row,
    captcha_token_valid,
    challenge_required,
    cleanup_share_verify_attempts,
    cleanup_terminal_shares,
    clear_verify_attempts,
    create_share as create_share_row,
    ensure_share_active,
    reserve_share_download,
    resource_in_publication_scope,
    reset_share_code,
    restore_share,
    share_status,
    target_valid_for_share,
    update_share_duration,
    verify_attempt_failed,
)
from .shares.ticket import create_share_ticket, share_cookie_name, validate_share_ticket
from .search import (
    SEARCH_OBJECT_TYPES,
    SEARCH_SORTS,
    SEARCH_TYPES,
    classify_match,
    normalize_search_query,
    rebuild_search_index,
    recover_search_index_if_dirty,
    search_index,
    set_search_index_dirty,
)
from .site_assets import SHARE_IMAGE_MAX_BYTES, remove_share_image, save_share_image, share_image_path
from .site import public_site_settings, router as site_router
from .sync.rolling import (
    migrate_existing_index_to_rolling,
    prepare_index_recovery,
    recover_rolling_state,
    resolve_rolling_mode,
    rolling_enabled,
    rolling_status,
    run_due_rolling_window,
)
from .users import router as users_router
from .userdata import router as userdata_router
from .sessions import (
    SESSION_CLEANUP_SECONDS,
    USER_SESSION_COOKIE,
    SessionValidationError,
    cleanup_expired_user_sessions,
    validate_user_session,
)


scheduler_task: asyncio.Task | None = None
manual_sync_task: asyncio.Task | None = None
SESSION_COOKIE = "cloudsite_session"
_storage_info_cache: dict = {"data": None, "fetched_at": 0.0}
_last_rate_limit_cleanup_at = 0.0
_last_session_cleanup_at = 0.0
_last_share_cleanup_at = 0.0
SHARE_CLEANUP_SECONDS = 3600
STORAGE_INFO_TTL_SECONDS = 600
SYNC_INTERVAL_OPTIONS = {180, 360, 720, 1440}
logger = logging.getLogger(__name__)


def create_session_token(username: str) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"username": username, "expires": int(time.time()) + 86400 * 7}, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def verify_session_token(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    payload, signature = token.rsplit(".", 1)
    expected = hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return False
    try:
        decoded = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return int(decoded.get("expires", 0)) > int(time.time())
    except Exception:
        return False


def alist_http_exception(exc: Exception, fallback_status: int = 502) -> HTTPException:
    if isinstance(exc, AListError):
        return HTTPException(exc.status_code, {"code": exc.code, "message": str(exc)})
    if isinstance(exc, ValueError):
        return HTTPException(400, {"code": "AL-006", "message": str(exc)})
    return HTTPException(fallback_status, {"code": "AL-999", "message": "AList 操作失败，请稍后重试"})


async def get_system_values(session) -> dict:
    rows = list((await session.scalars(select(SystemSetting))).all())
    values = {row.key: row.value for row in rows}
    interval = int(values.get("sync_interval_minutes", "360"))
    return {
        "automatic_sync": values.get("automatic_sync", "false") == "true",
        "sync_interval_minutes": interval if interval in SYNC_INTERVAL_OPTIONS else 360,
        "sync_on_startup": values.get("sync_on_startup", "false") == "true",
    }


async def _run_cleanup_job(action: str, label: str, cleanup) -> None:
    try:
        deleted = await cleanup()
        await log_operation(
            "maintenance",
            action,
            f"{label}完成：清理 {deleted} 条过期记录",
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        with suppress(Exception):
            await log_operation(
                "maintenance",
                f"{action}_failed",
                f"{label}失败：{type(exc).__name__}: {str(exc)[:900]}",
                level="ERROR",
            )


async def scheduler_loop() -> None:
    global _last_rate_limit_cleanup_at, _last_session_cleanup_at, _last_share_cleanup_at
    while True:
        await asyncio.sleep(60)
        monotonic_now = time.monotonic()
        if monotonic_now - _last_session_cleanup_at >= SESSION_CLEANUP_SECONDS:
            _last_session_cleanup_at = monotonic_now
            await _run_cleanup_job(
                "session_cleanup",
                "Session 清理",
                cleanup_expired_user_sessions,
            )
        if monotonic_now - _last_rate_limit_cleanup_at >= DOWNLOAD_RATE_CLEANUP_SECONDS:
            _last_rate_limit_cleanup_at = monotonic_now
            await _run_cleanup_job(
                "download_rate_cleanup",
                "下载限流清理",
                cleanup_download_rate_limits,
            )
        if monotonic_now - _last_share_cleanup_at >= SHARE_CLEANUP_SECONDS:
            _last_share_cleanup_at = monotonic_now
            await _run_cleanup_job("share_cleanup", "分享清理", cleanup_terminal_shares)
            await _run_cleanup_job("share_verify_attempt_cleanup", "分享验证码状态清理", cleanup_share_verify_attempts)
        async with StateSession() as session:
            values = await get_system_values(session)
        if not values["automatic_sync"]:
            continue
        try:
            if await migrate_existing_index_to_rolling():
                await run_due_rolling_window()
            elif await automatic_sync_due(values["sync_interval_minutes"]):
                # Freeze the existing first-index bootstrap path.  Rolling 1.1
                # is enabled only after this legacy full sync succeeds.
                await run_sync("scheduled")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await log_operation(
                "sync",
                "scheduler_failed",
                f"自动同步调度失败：{type(exc).__name__}: {str(exc)[:900]}",
                level="ERROR",
            )


async def _run_manual_sync_in_background(full: bool, force: bool) -> None:
    global manual_sync_task
    try:
        if await rolling_enabled():
            await run_due_rolling_window(manual=True)
        else:
            result = await run_sync("manual", full, force)
            if result.get("status") == "success":
                # The completed first index remains authoritative even if the
                # follow-up migration is temporarily unavailable.  The normal
                # scheduler retries this idempotent migration later.
                with suppress(Exception):
                    await migrate_existing_index_to_rolling()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        await log_operation("sync", "failed", f"后台同步启动失败：{str(exc)[:1000]}", level="ERROR")
    finally:
        manual_sync_task = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global scheduler_task, manual_sync_task
    validate_database_files()
    backup_stable_id_databases()
    await init_databases()
    validate_database_files()
    await recover_search_index_if_dirty()
    await recover_interrupted_sync_runs()
    await migrate_stable_resource_ids()
    await recover_rolling_state()
    await migrate_existing_index_to_rolling()
    if await resolve_rolling_mode() == "INDEX_RECOVERY_REQUIRED":
        await prepare_index_recovery()
    async with StateSession() as session:
        if not await session.get(SiteSettings, 1):
            session.add(SiteSettings(id=1))
        await session.commit()
        values = await get_system_values(session)
    scheduler_task = asyncio.create_task(scheduler_loop())
    if values["sync_on_startup"]:
        asyncio.create_task(_safe_startup_sync())
    yield
    if scheduler_task:
        scheduler_task.cancel()
        with suppress(asyncio.CancelledError):
            await scheduler_task
    if manual_sync_task and not manual_sync_task.done():
        manual_sync_task.cancel()
        with suppress(asyncio.CancelledError):
            await manual_sync_task


async def _safe_startup_sync():
    delay = random.uniform(
        settings.sync_startup_delay_min_seconds,
        settings.sync_startup_delay_max_seconds,
    )
    await asyncio.sleep(delay)
    async with StateSession() as session:
        values = await get_system_values(session)
    if not values["sync_on_startup"]:
        return
    with suppress(Exception):
        if await migrate_existing_index_to_rolling():
            await run_due_rolling_window()
        elif await automatic_sync_due(values["sync_interval_minutes"]):
            await run_sync("startup")


app = FastAPI(title="CloudSite API", version=__version__, lifespan=lifespan)


@app.exception_handler(StarletteHTTPException)
async def structured_http_error(_: Request, exc: StarletteHTTPException):
    if isinstance(exc.detail, dict) and isinstance(exc.detail.get("code"), str):
        detail = {
            "code": exc.detail["code"],
            "message": str(exc.detail.get("message") or "请求失败"),
        }
        for key, value in exc.detail.items():
            if key not in detail:
                detail[key] = value
    else:
        detail = {
            "code": f"HTTP_{exc.status_code}",
            "message": str(exc.detail or "请求失败"),
        }
    return JSONResponse({"detail": detail}, status_code=exc.status_code, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def structured_validation_error(_: Request, __: RequestValidationError):
    return JSONResponse(
        {"detail": {"code": "VALIDATION_ERROR", "message": "请求参数格式不正确"}},
        status_code=422,
    )


@app.exception_handler(Exception)
async def structured_internal_error(request: Request, exc: Exception):
    logger.error(
        "Unhandled API error on %s %s",
        request.method,
        request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return JSONResponse(
        {"detail": {"code": "INTERNAL_ERROR", "message": "服务器暂时无法处理请求"}},
        status_code=500,
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(userdata_router)
app.include_router(site_router)


@app.middleware("http")
async def admin_session_middleware(request: Request, call_next):
    path = request.url.path
    if request.method == "OPTIONS":
        return await call_next(request)

    if path.startswith("/api/admin"):
        if path.startswith("/api/admin/auth/"):
            return await call_next(request)
        async with StateSession() as session:
            connection = await session.get(AListConnection, 1)
        admin_authenticated = verify_session_token(request.cookies.get(SESSION_COOKIE))
        if path.startswith("/api/admin/users") and not admin_authenticated:
            return JSONResponse(
                {"detail": {"code": "ADMIN_REQUIRED", "message": "请先登录管理后台"}},
                status_code=403,
            )
        if connection and connection.enabled and not admin_authenticated:
            return JSONResponse(
                {"detail": {"code": "ADMIN_REQUIRED", "message": "请先登录管理后台"}},
                status_code=403,
            )
        return await call_next(request)

    public_api_paths = {"/api/health", "/api/auth/login", "/api/auth/register", "/api/site"}
    preview_ticket_valid = False
    if path.startswith("/p/"):
        resource_id = path.removeprefix("/p/")
        preview_ticket_valid = validate_preview_ticket(resource_id, request.query_params.get("ticket"))
    requires_user = not preview_ticket_valid and (
        (
            path.startswith("/api/")
            and path not in public_api_paths
            and not path.startswith("/api/public/shares/")
            and not path.startswith("/api/public/share-page")
        )
        or path.startswith("/d/")
        or (path.startswith("/p/") and not path.startswith("/s/"))
        or path.startswith("/office-files/")
    )
    if not requires_user:
        return await call_next(request)
    async with StateSession() as session:
        try:
            await validate_user_session(session, request.cookies.get(USER_SESSION_COOKIE))
            await session.commit()
        except SessionValidationError as exc:
            await session.commit()
            return JSONResponse(
                {"detail": {"code": exc.code, "message": exc.message}},
                status_code=exc.status_code,
            )
    return await call_next(request)


@app.get("/api/health")
async def health():
    return {"status": "healthy", "version": __version__, "database": "SQLite 3"}


@app.get("/api/admin/auth/status")
async def admin_auth_status(request: Request):
    async with StateSession() as session:
        connection = await session.get(AListConnection, 1)
    auth_required = bool(connection and connection.enabled)
    return {"auth_required": auth_required, "authenticated": not auth_required or verify_session_token(request.cookies.get(SESSION_COOKIE))}


@app.post("/api/admin/auth/login")
async def admin_login(payload: AdminLoginInput, request: Request, response: Response):
    async with StateSession() as session:
        connection = await session.get(AListConnection, 1)
    if not connection or not connection.enabled:
        raise HTTPException(409, "请先在系统页配置 AList")
    try:
        await AListClient(connection.base_url, payload.username, payload.password).test()
    except Exception as exc:
        raise HTTPException(401, "账号或密码错误") from exc
    response.set_cookie(
        SESSION_COOKIE,
        create_session_token(payload.username),
        max_age=86400 * 7,
        httponly=True,
        samesite="lax",
        secure=request_is_https(request),
        path="/",
    )
    return {"ok": True}


@app.post("/api/admin/auth/logout")
async def admin_logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


def resource_dict(row: Resource, parent: Folder | None = None) -> dict:
    payload = {
        "id": row.id,
        "name": row.name,
        "parent_id": row.parent_id,
        "content_type": row.content_type,
        "extension": row.extension,
        "mime_type": row.mime_type,
        "size": row.size,
        "modified_at": row.modified_at,
        "thumbnail": "",
    }
    if parent:
        payload["parent"] = {"id": parent.id, "name": parent.name}
    return payload


def folder_dict(row: Folder, include_path: bool = False) -> dict:
    payload = {
        "id": row.id,
        "name": row.name,
        "parent_id": row.parent_id,
        "content_type": row.content_type,
        "depth": row.depth,
        "child_folder_count": row.child_folder_count,
        "resource_count": row.resource_count,
        "modified_at": row.modified_at,
    }
    if include_path:
        payload["path"] = row.path
        payload["root_mapping_id"] = row.root_mapping_id
        payload["status"] = row.status
        payload["indexed_at"] = row.indexed_at
    return payload


def breadcrumbs_for(folder: Folder | None, folders_by_id: dict[str, Folder]) -> list[dict]:
    items: list[dict] = []
    current = folder
    visited: set[str] = set()
    while current and current.id not in visited:
        visited.add(current.id)
        items.append({"id": current.id, "name": current.name})
        current = folders_by_id.get(current.parent_id or "")
    return list(reversed(items))


async def collection_dict(state, index, row: Collection, include_items: bool = False) -> dict:
    items = list((await state.scalars(select(CollectionItem).where(CollectionItem.collection_id == row.id).order_by(CollectionItem.sort_order, CollectionItem.id))).all())
    resource_ids = [item.resource_id for item in items]
    resources_by_id = {}
    if resource_ids:
        resources_by_id = {
            resource.id: resource
            for resource in (
                await index.scalars(
                    select(Resource).where(Resource.id.in_(resource_ids), Resource.status == "active")
                )
            ).all()
        }
    payload = {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "cover": row.cover,
        "status": row.status,
        "visible_on_home": row.visible_on_home,
        "sort_order": row.sort_order,
        "item_count": len(resources_by_id),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
    if include_items:
        payload["items"] = [resource_dict(resources_by_id[item.resource_id]) for item in items if item.resource_id in resources_by_id]
    return payload


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


def site_settings_dict(row: SiteSettings) -> dict:
    return {
        **public_site_settings(row),
        "share_image_url": "/api/public/share-page/image" if row.share_image_name else "",
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
        child_folders = list((await index.scalars(select(Folder).where(Folder.parent_id == target.id, Folder.status == "active").order_by(Folder.name))).all())
        child_resources = list((await index.scalars(select(Resource).where(Resource.parent_id == target.id, Resource.status == "active").order_by(Resource.name))).all())
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


@app.get("/api/home")
async def home():
    async with StateSession() as state, IndexSession() as index:
        site = await state.get(SiteSettings, 1)
        root_rows = list((await state.scalars(select(ContentRootMapping).where(ContentRootMapping.enabled.is_(True)).order_by(ContentRootMapping.sort_order, ContentRootMapping.id))).all())
        counts = {}
        for content_type in ("software", "image", "video", "document", "file"):
            counts[content_type] = int(await index.scalar(select(func.count()).select_from(Resource).where(Resource.content_type == content_type, Resource.status == "active")) or 0)
        recent = list((await index.scalars(select(Resource).where(Resource.status == "active").order_by(desc(Resource.modified_at)).limit(site.recent_limit if site else 6))).all())
        popular = list((await index.scalars(select(Resource).where(Resource.status == "active").order_by(desc(Resource.size), desc(Resource.modified_at)).limit(site.popular_limit if site else 6))).all())
        collections = list((await state.scalars(select(Collection).where(Collection.visible_on_home.is_(True), Collection.status == "active").order_by(Collection.sort_order, desc(Collection.updated_at)).limit(site.collection_limit if site else 4))).all())
        content_roots = []
        for root in root_rows:
            content_roots.append({
                "id": root.id,
                "content_type": root.content_type,
                "display_name": root.display_name,
                "resource_count": int(await index.scalar(select(func.count()).select_from(Resource).where(Resource.root_mapping_id == root.id, Resource.status == "active")) or 0),
                "folder_count": int(await index.scalar(select(func.count()).select_from(Folder).where(Folder.root_mapping_id == root.id, Folder.status == "active")) or 0),
                "sort_order": root.sort_order,
            })
        resource_count = int(await index.scalar(select(func.count()).select_from(Resource).where(Resource.status == "active")) or 0)
        folder_count = int(await index.scalar(select(func.count()).select_from(Folder).where(Folder.status == "active")) or 0)
        total_size = int(await index.scalar(select(func.coalesce(func.sum(Resource.size), 0)).where(Resource.status == "active")) or 0)
        return {
            "site": {"site_name": site.site_name, "home_title": site.home_title, "description": site.description},
            "content_roots": content_roots,
            "stats": {"resource_count": resource_count, "folder_count": folder_count, "total_size": total_size},
            "recent_resources": [resource_dict(row) for row in recent],
            "counts": counts,
            "recent": [resource_dict(row) for row in recent],
            "popular": [resource_dict(row) for row in popular],
            "collections": [await collection_dict(state, index, row) for row in collections],
        }


@app.get("/api/storage/info")
async def storage_info():
    now = time.time()
    if _storage_info_cache["data"] is not None and (now - _storage_info_cache["fetched_at"]) < STORAGE_INFO_TTL_SECONDS:
        return _storage_info_cache["data"]
    async with StateSession() as session:
        connection = await session.get(AListConnection, 1)
    if not connection or not connection.enabled:
        info = {"primary": "网盘", "drives": []}
    else:
        try:
            password = decrypt_secret(connection.password_ciphertext)
            async with AListClient(connection.base_url, connection.username, password) as client:
                info = await client.get_storage_info(connection.base_path or "")
        except Exception:
            info = {"primary": "网盘", "drives": []}
    _storage_info_cache["data"] = info
    _storage_info_cache["fetched_at"] = now
    return info


@app.get("/api/content-roots", response_model=ContentRootListOutput)
async def public_content_roots():
    async with StateSession() as state, IndexSession() as index:
        roots = list((await state.scalars(select(ContentRootMapping).where(ContentRootMapping.enabled.is_(True)).order_by(ContentRootMapping.sort_order, ContentRootMapping.id))).all())
        items = []
        for root in roots:
            items.append({
                "id": root.id,
                "content_type": root.content_type,
                "display_name": root.display_name,
                "resource_count": int(await index.scalar(select(func.count()).select_from(Resource).where(Resource.root_mapping_id == root.id, Resource.status == "active")) or 0),
                "folder_count": int(await index.scalar(select(func.count()).select_from(Folder).where(Folder.root_mapping_id == root.id, Folder.status == "active")) or 0),
                "sort_order": root.sort_order,
            })
        return {"items": items}


@app.get("/api/resources", response_model=ResourcePageOutput)
async def resources(
    resource_type: str | None = Query(None, alias="type"),
    content_type: str | None = None,
    folder_id: str | None = None,
    parent_id: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    sort: str = "modified_at",
    order: str = "desc",
):
    selected_type = resource_type or content_type
    selected_folder = folder_id or parent_id
    sort_columns = {"name": Resource.name, "modified_at": Resource.modified_at, "modified": Resource.modified_at, "size": Resource.size}
    if sort not in sort_columns or order not in {"asc", "desc"}:
        raise HTTPException(400, {"code": "API-001", "message": "排序参数无效"})
    async with IndexSession() as session:
        query = select(Resource).where(Resource.status == "active")
        count_query = select(func.count()).select_from(Resource).where(Resource.status == "active")
        if selected_type:
            query = query.where(Resource.content_type == selected_type)
            count_query = count_query.where(Resource.content_type == selected_type)
        if selected_folder:
            query = query.where(Resource.parent_id == selected_folder)
            count_query = count_query.where(Resource.parent_id == selected_folder)
        order_by = sort_columns[sort].asc() if order == "asc" else sort_columns[sort].desc()
        total = int(await session.scalar(count_query) or 0)
        rows = list((await session.scalars(query.order_by(order_by, Resource.id).offset((page - 1) * page_size).limit(page_size))).all())
        parent_ids = {row.parent_id for row in rows if row.parent_id}
        parents = {row.id: row for row in (await session.scalars(select(Folder).where(Folder.id.in_(parent_ids), Folder.status == "active"))).all()} if parent_ids else {}
        return {"items": [resource_dict(row, parents.get(row.parent_id or "")) for row in rows], "total": total, "page": page, "page_size": page_size, "total_pages": math.ceil(total / page_size) if total else 0}


@app.get("/api/resources/{resource_id}", response_model=ResourceDetailOutput)
async def resource_detail(resource_id: str):
    async with IndexSession() as session:
        row = await session.get(Resource, resource_id)
        if not row or row.status != "active":
            raise HTTPException(404, {"code": "RS-001", "message": "资源不存在或已不可用"})
        parent = await session.get(Folder, row.parent_id) if row.parent_id else None
        all_folders = {item.id: item for item in (await session.scalars(select(Folder).where(Folder.status == "active"))).all()}
        related = list((await session.scalars(select(Resource).where(Resource.status == "active", Resource.parent_id == row.parent_id, Resource.id != row.id).order_by(desc(Resource.modified_at)).limit(8))).all())
        siblings = list((await session.scalars(select(Resource).where(Resource.status == "active", Resource.parent_id == row.parent_id, Resource.content_type == row.content_type).order_by(Resource.name, Resource.id))).all())
        sibling_index = next((index for index, item in enumerate(siblings) if item.id == row.id), -1)
        previous = siblings[sibling_index - 1] if sibling_index > 0 else None
        next_item = siblings[sibling_index + 1] if sibling_index >= 0 and sibling_index + 1 < len(siblings) else None
        return {
            **resource_dict(row, parent),
            "breadcrumbs": breadcrumbs_for(parent, all_folders),
            "related": [resource_dict(item, parent) for item in related],
            "capabilities": preview_capability(row),
            "previous": resource_dict(previous, parent) if previous else None,
            "next": resource_dict(next_item, parent) if next_item else None,
        }


@app.get("/api/resources/{resource_id}/preview")
async def resource_preview_capability(resource_id: str):
    async with IndexSession() as session:
        resource = await session.get(Resource, resource_id)
        if not resource or resource.status != "active":
            raise HTTPException(404, {"code": "PV-001", "message": "资源不存在或已不可用"})
        return preview_capability(resource)


@app.get("/api/resources/{resource_id}/text-preview", response_model=TextPreviewOutput)
async def resource_text_preview(resource_id: str):
    async with IndexSession() as index, StateSession() as state:
        resource = await index.get(Resource, resource_id)
        if not resource or resource.status != "active":
            raise HTTPException(404, {"code": "PV-001", "message": "资源不存在或已不可用"})
        connection = await state.get(AListConnection, 1)
        try:
            return await load_text_preview(resource, connection)
        except PreviewError as exc:
            raise HTTPException(exc.status_code, {"code": exc.code, "message": exc.message}) from exc


@app.get("/api/resources/{resource_id}/office-preview")
async def resource_office_preview(resource_id: str):
    async with IndexSession() as index, StateSession() as state:
        resource = await index.get(Resource, resource_id)
        if not resource or resource.status != "active":
            raise HTTPException(404, {"code": "PV-001", "message": "资源不存在或已不可用"})
        if preview_capability(resource)["preview_type"] != "office":
            raise HTTPException(400, {"code": "PV-002", "message": "该资源不支持 Office 在线预览"})
        connection = await state.get(AListConnection, 1)
        try:
            await ensure_preview_cached(resource, connection)
        except OfficePreviewError as exc:
            raise HTTPException(exc.status_code, {"code": exc.code, "message": exc.message}) from exc
        return {"url": f"/office-files/{office_cache_filename(resource)}"}


@app.get("/api/resources/{resource_id}/pdf-preview")
async def resource_pdf_preview(resource_id: str):
    async with IndexSession() as index, StateSession() as state:
        resource = await index.get(Resource, resource_id)
        if not resource or resource.status != "active":
            raise HTTPException(404, {"code": "PV-001", "message": "资源不存在或已不可用"})
        if preview_capability(resource)["preview_type"] != "pdf":
            raise HTTPException(400, {"code": "PV-002", "message": "该资源不支持 PDF 在线预览"})
        connection = await state.get(AListConnection, 1)
        try:
            await ensure_preview_cached(resource, connection)
        except OfficePreviewError as exc:
            raise HTTPException(exc.status_code, {"code": exc.code, "message": exc.message}) from exc
        return {"url": f"/office-files/{office_cache_filename(resource)}"}


@app.get("/office-files/{filename}")
async def serve_office_file(filename: str):
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, "无效的预览文件名")
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    path = settings.office_cache_dir / filename
    if not path.is_file():
        raise HTTPException(404, "预览文件不存在或已过期")
    return FileResponse(path, media_type=office_content_type(extension), filename=filename, content_disposition_type="inline")


@app.get("/api/folders", response_model=FolderListOutput)
async def folders(content_type: str | None = None, parent_id: str | None = None):
    async with IndexSession() as session:
        query = select(Folder).where(Folder.status == "active")
        if content_type:
            query = query.where(Folder.content_type == content_type)
        if parent_id is not None:
            query = query.where(Folder.parent_id == (parent_id or None))
        rows = list((await session.scalars(query.order_by(Folder.depth, Folder.name))).all())
        return {"items": [folder_dict(row) for row in rows]}


@app.get("/api/folders/{folder_id}", response_model=FolderDetailOutput)
async def folder_detail(
    folder_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    sort: str = "name",
    order: str = "asc",
):
    sort_columns = {"name": Resource.name, "modified_at": Resource.modified_at, "size": Resource.size}
    if sort not in sort_columns or order not in {"asc", "desc"}:
        raise HTTPException(400, {"code": "API-001", "message": "排序参数无效"})
    async with IndexSession() as session:
        row = await session.get(Folder, folder_id)
        if not row or row.status != "active":
            raise HTTPException(404, {"code": "FD-001", "message": "文件夹不存在或已不可用"})
        all_folders = {item.id: item for item in (await session.scalars(select(Folder).where(Folder.status == "active"))).all()}
        child_folders = list((await session.scalars(select(Folder).where(Folder.parent_id == folder_id, Folder.status == "active").order_by(Folder.name))).all())
        resource_query = select(Resource).where(Resource.parent_id == folder_id, Resource.status == "active")
        total = int(await session.scalar(select(func.count()).select_from(Resource).where(Resource.parent_id == folder_id, Resource.status == "active")) or 0)
        order_by = sort_columns[sort].asc() if order == "asc" else sort_columns[sort].desc()
        child_resources = list((await session.scalars(resource_query.order_by(order_by, Resource.id).offset((page - 1) * page_size).limit(page_size))).all())
        return {
            "folder": folder_dict(row),
            "breadcrumbs": breadcrumbs_for(row, all_folders),
            "child_folders": [folder_dict(item) for item in child_folders],
            "resources": {"items": [resource_dict(item, row) for item in child_resources], "page": page, "page_size": page_size, "total": total, "total_pages": math.ceil(total / page_size) if total else 0},
        }


@app.get("/api/search", response_model=SearchOutput)
async def search(
    q: str = "",
    resource_type: str | None = Query(default=None, alias="type"),
    object_type: str = "all",
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    sort: str = "relevance",
):
    normalized = normalize_search_query(q)
    if not normalized:
        raise HTTPException(400, {"code": "SRCH-001", "message": "搜索关键词为空"})
    if len(normalized) > 200:
        raise HTTPException(400, {"code": "SRCH-002", "message": "搜索关键词过长"})
    if resource_type is not None and resource_type not in SEARCH_TYPES:
        raise HTTPException(400, {"code": "SRCH-004", "message": "资源类型无效"})
    if object_type not in SEARCH_OBJECT_TYPES or sort not in SEARCH_SORTS:
        raise HTTPException(400, {"code": "SRCH-004", "message": "搜索参数无效"})
    try:
        async with IndexSession() as session:
            candidates, total = await search_index(session, normalized, resource_type, object_type, page, page_size, sort)
            resource_ids = [row["object_id"] for row in candidates if row["object_type"] == "resource"]
            folder_ids = [row["object_id"] for row in candidates if row["object_type"] == "folder"]
            resources_by_id = {
                row.id: row for row in (await session.scalars(select(Resource).where(Resource.id.in_(resource_ids), Resource.status == "active"))).all()
            } if resource_ids else {}
            folders_by_id = {
                row.id: row for row in (await session.scalars(select(Folder).where(Folder.id.in_(folder_ids), Folder.status == "active"))).all()
            } if folder_ids else {}
            all_folders = {
                row.id: row for row in (await session.scalars(select(Folder).where(Folder.status == "active"))).all()
            }
            items = []
            for candidate in candidates:
                if candidate["object_type"] == "resource":
                    row = resources_by_id.get(candidate["object_id"])
                    if not row:
                        continue
                    parent = all_folders.get(row.parent_id) if row.parent_id else None
                    payload = resource_dict(row, parent)
                    payload.update({
                        "object_type": "resource",
                        "breadcrumbs": breadcrumbs_for(parent, all_folders) if parent else [],
                        "child_folder_count": 0,
                        "resource_count": 0,
                        "match_type": classify_match(row.name, normalized),
                    })
                else:
                    row = folders_by_id.get(candidate["object_id"])
                    if not row:
                        continue
                    payload = folder_dict(row)
                    payload.update({
                        "object_type": "folder",
                        "extension": "",
                        "size": None,
                        "parent": None,
                        "breadcrumbs": breadcrumbs_for(row, all_folders),
                        "thumbnail": "",
                        "match_type": classify_match(row.name, normalized),
                    })
                items.append(payload)
            return {
                "query": normalized,
                "filters": {"type": resource_type, "object_type": object_type, "sort": sort},
                "items": items,
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": math.ceil(total / page_size) if total else 0,
            }
    except HTTPException:
        raise
    except Exception as exc:
        await log_operation("search", "query_failed", type(exc).__name__, level="ERROR")
        raise HTTPException(503, {"code": "SRCH-003", "message": "搜索索引暂时不可用"}) from exc


@app.get("/api/collections")
async def public_collections():
    async with StateSession() as state, IndexSession() as index:
        rows = list((await state.scalars(select(Collection).where(Collection.status == "active").order_by(Collection.sort_order, Collection.name))).all())
        return {"items": [await collection_dict(state, index, row) for row in rows]}


@app.get("/api/collections/{collection_id}")
async def public_collection_detail(collection_id: int):
    async with StateSession() as state, IndexSession() as index:
        row = await state.get(Collection, collection_id)
        if not row or row.status != "active":
            raise HTTPException(404, "合集不存在")
        return await collection_dict(state, index, row, include_items=True)


@app.get("/api/shares/{token}")
async def public_share(token: str):
    async with StateSession() as state, IndexSession() as index:
        row = await state.get(Share, token)
        if not row or not row.enabled or share_is_expired(row):
            raise HTTPException(410, "分享不存在、已关闭或已过期")
        if row.object_type == "resource":
            target = await index.get(Resource, row.object_id)
            if not target or target.status != "active":
                raise HTTPException(404, "分享的资源不存在")
            payload = resource_dict(target)
        elif row.object_type == "folder":
            target = await index.get(Folder, row.object_id)
            if not target or target.status != "active":
                raise HTTPException(404, "分享的文件夹不存在")
            child_folders = list((await index.scalars(select(Folder).where(Folder.parent_id == target.id, Folder.status == "active").order_by(Folder.name))).all())
            child_resources = list((await index.scalars(select(Resource).where(Resource.parent_id == target.id, Resource.status == "active").order_by(Resource.name))).all())
            payload = {"folder": folder_dict(target), "folders": [folder_dict(item) for item in child_folders], "resources": [resource_dict(item) for item in child_resources]}
        else:
            target = await state.get(Collection, int(row.object_id)) if row.object_id.isdigit() else None
            if not target:
                raise HTTPException(404, "分享的合集不存在")
            payload = await collection_dict(state, index, target, include_items=True)
        row.access_count += 1
        row.last_accessed_at = utcnow()
        await state.commit()
        return {"share": share_dict(row), "target": payload}


@app.get("/api/public/share-page")
async def public_share_page_settings():
    async with StateSession() as state:
        row = await state.get(SiteSettings, 1) or SiteSettings(id=1)
        return {
            "site_name": row.site_name or "CloudSite",
            "share_image_url": "/api/public/share-page/image" if row.share_image_name else "",
        }


@app.get("/api/public/share-page/image")
async def public_share_page_image():
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


@app.get("/api/public/shares/{token}")
async def public_share_meta(token: str):
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


@app.post("/api/public/shares/{token}/verify")
async def public_share_verify(token: str, payload: ShareVerifyInput, request: Request, response: Response):
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


@app.get("/api/public/shares/{token}/content")
async def public_share_content(token: str, request: Request):
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
        connection = await state.get(AListConnection, 1)
        try:
            resolution = await resolve_download_entry(resource, connection)
            await reserve_share_download(state, row.token)
            await _download_event(state, resource.id, "success", None, started, source="share")
            return RedirectResponse(resolution.url, status_code=302)
        except DownloadError as exc:
            await _download_event(state, resource.id, "failed", exc.code, started, source="share")
            raise HTTPException(exc.status_code, {"code": exc.code, "message": exc.message}) from exc


@app.get("/api/public/shares/{token}/download")
async def public_share_download(token: str, request: Request):
    return await _share_download_response(token, request)


@app.get("/api/public/shares/{token}/download/{resource_id}")
async def public_share_download_resource(token: str, resource_id: str, request: Request):
    return await _share_download_response(token, request, resource_id)


@app.get("/s/{token}")
async def short_share_direct_download(token: str, request: Request):
    async with StateSession() as state:
        row = await state.get(Share, token)
        if not row:
            raise HTTPException(404, {"code": "SHARE_NOT_FOUND", "message": "分享不存在"})
        if row.access_mode != "direct":
            raise HTTPException(409, {"code": "SHARE_CODE_REQUIRED", "message": "请通过分享页面输入分享码"})
    return await _share_download_response(token, request)


@app.get("/s/{token}/d")
async def short_share_download(token: str, request: Request):
    return await _share_download_response(token, request)


@app.get("/s/{token}/d/{resource_id}")
async def short_share_download_resource(token: str, resource_id: str, request: Request):
    return await _share_download_response(token, request, resource_id)


@app.get("/d/{resource_id}")
async def download(resource_id: str, request: Request):
    started = time.perf_counter()
    wants_json = "application/json" in request.headers.get("accept", "").lower()
    async with IndexSession() as index, StateSession() as state:
        if not validate_resource_id(resource_id):
            await _download_event(state, resource_id[:64], "failed", "DL-001", started)
            return _download_error_redirect("DL-001", resource_id[:64])
        resource = await index.get(Resource, resource_id)
        if not resource or resource.status == "missing":
            await _download_event(state, resource_id, "failed", "DL-001", started)
            return _download_error_redirect("DL-001", resource_id)
        if resource.status != "active":
            await _download_event(state, resource_id, "failed", "DL-007", started)
            return _download_error_redirect("DL-007", resource_id)
        rate = await check_download_rate(get_effective_client_ip(request))
        if not rate.allowed:
            await _download_event(state, resource_id, "failed", "DOWNLOAD_RATE_LIMITED", started)
            return JSONResponse(
                rate_limit_payload(rate),
                status_code=429,
                headers={"Retry-After": str(rate.retry_after)},
            )
        connection = await state.get(AListConnection, 1)
        try:
            resolution = await resolve_download_entry(resource, connection)
            await _download_event(state, resource_id, "success", None, started)
            if wants_json:
                return {"url": resolution.url}
            return RedirectResponse(resolution.url, status_code=302)
        except DownloadError as exc:
            await _download_event(state, resource_id, "failed", exc.code, started)
            return _download_error_redirect(exc.code, resource_id)


def _download_error_redirect(code: str, resource_id: str) -> RedirectResponse:
    return RedirectResponse(f"/download-error?{urlencode({'code': code, 'resource': resource_id})}", status_code=302)


async def _download_event(session, resource_id, result, code, started, source: str = "public"):
    session.add(DownloadEvent(resource_id=resource_id, result=result, error_code=code, duration_ms=int((time.perf_counter() - started) * 1000), source=source))
    await session.commit()


@app.get("/p/{resource_id}")
async def preview(resource_id: str, refresh: bool = False):
    started = time.perf_counter()
    if not validate_resource_id(resource_id):
        return _preview_error_redirect(resource_id[:64], "PV-001")
    async with IndexSession() as index, StateSession() as state:
        resource = await index.get(Resource, resource_id)
        if not resource or resource.status != "active":
            return _preview_error_redirect(resource_id, "PV-001")
        connection = await state.get(AListConnection, 1)
        try:
            resolve_started = time.perf_counter()
            resolution = await resolve_preview_url(resource, connection, force_refresh=refresh)
            resolve_ms = (time.perf_counter() - resolve_started) * 1000
            redirect_ms = (time.perf_counter() - started) * 1000
            logger.debug(
                "preview metrics resource_id=%s preview_resolve_ms=%.2f preview_redirect_ms=%.2f cache_hit=%s",
                resource_id,
                resolve_ms,
                redirect_ms,
                getattr(resolution, "cache_hit", False),
            )
            return RedirectResponse(resolution.url, status_code=302)
        except PreviewError as exc:
            return _preview_error_redirect(resource.id, exc.code)


def _preview_error_redirect(resource_id: str, code: str) -> RedirectResponse:
    return RedirectResponse(f"/resource/{resource_id}?{urlencode({'preview_error': code})}", status_code=302)


@app.get("/api/admin/overview")
async def admin_overview():
    async with StateSession() as state, IndexSession() as index:
        resource_total = int(await index.scalar(select(func.count()).select_from(Resource).where(Resource.status == "active")) or 0)
        folder_total = int(await index.scalar(select(func.count()).select_from(Folder).where(Folder.status == "active")) or 0)
        failures = int(await state.scalar(select(func.count()).select_from(DownloadEvent).where(DownloadEvent.result == "failed")) or 0)
        connection = await state.get(AListConnection, 1)
        latest_sync = await index.scalar(select(SyncRun).order_by(desc(SyncRun.id)).limit(1))
        logs = list((await state.scalars(select(OperationLog).order_by(desc(OperationLog.id)).limit(6))).all())
        type_counts = {}
        for kind in ("software", "image", "video", "document", "file"):
            type_counts[kind] = int(await index.scalar(select(func.count()).select_from(Resource).where(Resource.content_type == kind, Resource.status == "active")) or 0)
        circuit = await sync_circuit_status()
        return {
            "resources": resource_total,
            "folders": folder_total,
            "download_failures": failures,
            "alist_connected": bool(connection and connection.enabled and connection.last_test_status == "success"),
            "latest_sync": None if not latest_sync else {
                "id": latest_sync.id,
                "status": latest_sync.status,
                "finished_at": latest_sync.finished_at,
                "added": latest_sync.added_count,
                "updated": latest_sync.updated_count,
                "removed": latest_sync.removed_count,
                "folders_scanned": latest_sync.folders_scanned,
                "resources_scanned": latest_sync.resources_scanned,
                "current_path": latest_sync.current_path,
                "roots_total": latest_sync.roots_total,
                "roots_completed": latest_sync.roots_completed,
                "roots_failed": latest_sync.roots_failed,
                "duration_ms": latest_sync.duration_ms,
            },
            "sync_circuit": {
                "open": circuit["open"],
                "until": circuit["until"],
                "reason": circuit["reason"],
            },
            "type_counts": type_counts,
            "logs": [{"level": row.level, "message": row.message, "created_at": row.created_at} for row in logs],
        }


def download_diagnostic_dict(row: DownloadDiagnostic) -> dict:
    return {
        "id": row.id,
        "resource_id": row.resource_id,
        "status": row.status,
        "failed_step": row.failed_step,
        "error_code": row.error_code,
        "message": row.message,
        "duration_ms": row.duration_ms,
        "target_host": row.target_host,
        "created_at": row.created_at,
    }


@app.post("/api/admin/downloads/diagnose")
async def diagnose_download(payload: DownloadDiagnosticInput):
    started = time.perf_counter()
    steps: list[dict] = []
    async with IndexSession() as index, StateSession() as state:
        resource = await index.get(Resource, payload.resource_id)
        if not resource:
            steps.append({"name": "resource_lookup", "status": "failed", "duration_ms": 0})
            diagnostic = DownloadDiagnostic(resource_id=payload.resource_id, status="failed", failed_step="resource_lookup", error_code="DL-001", message="资源不存在或已失效", duration_ms=int((time.perf_counter() - started) * 1000))
            state.add(diagnostic)
            await state.commit()
            return {**download_diagnostic_dict(diagnostic), "resource_name": "", "has_sign": False, "base_path": "", "steps": steps}
        steps.append({"name": "resource_lookup", "status": "success", "duration_ms": 0})
        if resource.status != "active":
            code = "DL-001" if resource.status == "missing" else "DL-007"
            steps.append({"name": "resource_status", "status": "failed", "duration_ms": 0})
            diagnostic = DownloadDiagnostic(resource_id=resource.id, status="failed", failed_step="resource_status", error_code=code, message="资源不存在或当前禁止下载", duration_ms=int((time.perf_counter() - started) * 1000))
            state.add(diagnostic)
            await state.commit()
            return {**download_diagnostic_dict(diagnostic), "resource_name": resource.name, "has_sign": False, "base_path": "", "steps": steps}
        steps.append({"name": "resource_status", "status": "success", "duration_ms": 0})
        connection = await state.get(AListConnection, 1)
        try:
            resolution = await resolve_download_entry(resource, connection)
            steps.extend(resolution.steps)
            diagnostic = DownloadDiagnostic(resource_id=resource.id, status="success", message="下载跳转已就绪", duration_ms=int((time.perf_counter() - started) * 1000), target_host=resolution.target_host)
            state.add(diagnostic)
            await state.commit()
            return {**download_diagnostic_dict(diagnostic), "resource_name": resource.name, "has_sign": resolution.has_sign, "base_path": resolution.base_path, "steps": steps}
        except DownloadError as exc:
            steps.append({"name": exc.failed_step, "status": "failed", "duration_ms": int((time.perf_counter() - started) * 1000)})
            diagnostic = DownloadDiagnostic(resource_id=resource.id, status="failed", failed_step=exc.failed_step, error_code=exc.code, message=exc.message, duration_ms=int((time.perf_counter() - started) * 1000))
            state.add(diagnostic)
            await state.commit()
            return {**download_diagnostic_dict(diagnostic), "resource_name": resource.name, "has_sign": False, "base_path": "", "steps": steps}


@app.get("/api/admin/downloads/diagnostics")
async def download_diagnostic_history(limit: int = Query(20, ge=1, le=100)):
    async with StateSession() as session:
        rows = list((await session.scalars(select(DownloadDiagnostic).order_by(desc(DownloadDiagnostic.id)).limit(limit))).all())
        return {"items": [download_diagnostic_dict(row) for row in rows]}


def require_explicit_admin(request: Request) -> None:
    if not verify_session_token(request.cookies.get(SESSION_COOKIE)):
        raise HTTPException(
            status_code=403,
            detail={"code": "ADMIN_REQUIRED", "message": "请先登录管理后台"},
        )


@app.get("/api/admin/identities/stats")
async def identity_stats(request: Request):
    require_explicit_admin(request)
    async with StateSession() as state:
        total = int(await state.scalar(select(func.count()).select_from(ResourceIdentity)) or 0)
        legacy = int(
            await state.scalar(
                select(func.count())
                .select_from(ResourceIdentity)
                .where(ResourceIdentity.created_from == "legacy_migration")
            )
            or 0
        )
        history_rows = (
            await state.execute(
                select(ResourceIdentityHistory.event_type, func.count())
                .group_by(ResourceIdentityHistory.event_type)
            )
        ).all()
    history = {event_type: int(count) for event_type, count in history_rows}
    async with IndexSession() as index:
        candidate_rows = (
            await index.execute(
                select(ResourceIdentityCandidate.status, func.count())
                .group_by(ResourceIdentityCandidate.status)
            )
        ).all()
    candidates = {status: int(count) for status, count in candidate_rows}
    return {
        "total": total,
        "legacy_seeded": legacy,
        "random_new": total - legacy,
        "rename_preserved": history.get("rename", 0),
        "move_preserved": history.get("move", 0),
        "pending": candidates.get("pending", 0),
        "ambiguous": candidates.get("ambiguous", 0),
        "manual_repairs": history.get("manual_repair", 0),
    }


@app.get("/api/admin/identities/candidates")
async def identity_candidates(
    request: Request,
    status: str = Query("open", pattern="^(open|pending|ambiguous|resolved_move|resolved_new|cancelled)$"),
    limit: int = Query(50, ge=1, le=200),
):
    require_explicit_admin(request)
    statement = select(ResourceIdentityCandidate).order_by(ResourceIdentityCandidate.id.desc()).limit(limit)
    if status == "open":
        statement = statement.where(ResourceIdentityCandidate.status.in_(("pending", "ambiguous")))
    else:
        statement = statement.where(ResourceIdentityCandidate.status == status)
    async with IndexSession() as index:
        rows = list((await index.scalars(statement)).all())
    return {
        "items": [
            {
                "id": row.id,
                "cycle_id": row.cycle_id,
                "observed_path": row.observed_path,
                "matched_resource_id": row.matched_resource_id,
                "candidate_resource_ids": json.loads(row.candidate_resource_ids_json or "[]"),
                "match_type": row.match_type,
                "confidence": row.confidence,
                "status": row.status,
                "size": row.size,
                "modified_at": row.modified_at,
                "extension": row.extension,
                "mime_type": row.mime_type,
                "fingerprint": row.fingerprint,
                "created_at": row.created_at,
                "resolved_at": row.resolved_at,
            }
            for row in rows
        ]
    }


@app.get("/api/admin/alist")
async def get_alist():
    async with StateSession() as session:
        row = await session.get(AListConnection, 1)
        if not row:
            return {"base_url": "", "username": "", "remember_credentials": True, "enabled": False, "connection_status": "unconfigured", "last_test_status": "untested", "last_test_message": "", "last_test_at": None, "has_password": False}
        return {"base_url": row.base_url, "username": row.username, "remember_credentials": row.remember_credentials, "enabled": row.enabled, "connection_status": "connected" if row.enabled and row.last_test_status == "success" else "disconnected", "last_test_status": row.last_test_status, "last_test_message": row.last_test_message, "last_test_at": row.last_test_at, "has_password": bool(row.password_ciphertext)}


@app.post("/api/admin/alist/test")
async def test_alist(payload: AListInput):
    async with StateSession() as session:
        row = await session.get(AListConnection, 1)
        password = payload.password
        try:
            if not password and row and row.password_ciphertext:
                password = decrypt_secret(row.password_ciphertext)
            if not password:
                raise AListError("请输入 AList 密码", "AL-004", status_code=400, auth_failed=True)
            result = await AListClient(payload.base_url, payload.username, password).test()
        except Exception as exc:
            status_row = row or AListConnection(id=1)
            status_row.last_test_status = "failed"
            status_row.last_test_message = str(exc)
            status_row.last_test_at = utcnow()
            session.add(status_row)
            session.add(OperationLog(level="ERROR", module="alist", action="test", message=f"AList 连接测试失败：{str(exc)[:300]}"))
            await session.commit()
            raise alist_http_exception(exc, 400) from exc
        status_row = row or AListConnection(id=1)
        status_row.last_test_status = "success"
        status_row.last_test_message = result["message"]
        status_row.last_test_at = utcnow()
        status_row.base_path = result.get("base_path") or "/"
        session.add(status_row)
        session.add(OperationLog(module="alist", action="test", message=f"AList 连接测试成功，根目录包含 {result['item_count']} 项"))
        await session.commit()
        return result


@app.put("/api/admin/alist")
async def save_alist(payload: AListInput):
    async with StateSession() as session:
        row = await session.get(AListConnection, 1) or AListConnection(id=1)
        password = payload.password
        if not password and row.password_ciphertext:
            try:
                password = decrypt_secret(row.password_ciphertext)
            except ValueError as exc:
                raise alist_http_exception(exc, 400) from exc
        if not password:
            raise HTTPException(400, "请输入 AList 密码")
        try:
            result = await AListClient(payload.base_url, payload.username, password).test()
        except Exception as exc:
            row.last_test_status = "failed"
            row.last_test_message = str(exc)
            row.last_test_at = utcnow()
            session.add(row)
            await session.commit()
            session.add(OperationLog(level="ERROR", module="alist", action="save", message=f"AList 设置验证失败：{str(exc)[:300]}"))
            await session.commit()
            raise alist_http_exception(exc, 400) from exc
        row.base_url = payload.base_url.rstrip("/")
        row.base_path = result.get("base_path") or "/"
        row.username = payload.username
        row.password_ciphertext = encrypt_secret(password) if payload.remember_credentials else ""
        row.remember_credentials = payload.remember_credentials
        row.enabled = True
        row.last_test_status = "success"
        row.last_test_message = "AList 连接及根目录访问成功"
        row.last_test_at = utcnow()
        session.add(row)
        session.add(OperationLog(module="alist", action="save", message="AList 连接设置已验证并保存"))
        await session.commit()
        return {"ok": True, "message": "AList 设置已保存"}


@app.get("/api/admin/alist/directories")
async def browse_alist_directories(path: str = Query("/", min_length=1, max_length=1000)):
    normalized_path = "/" + path.strip().strip("/")
    if normalized_path == "//":
        normalized_path = "/"
    async with StateSession() as session:
        row = await session.get(AListConnection, 1)
    if not row or not row.enabled:
        raise HTTPException(409, "请先连接并保存 AList 设置")
    if not row.password_ciphertext:
        raise HTTPException(409, "当前未保存 AList 登录凭据，请重新保存连接并启用记住登录信息")
    try:
        client = AListClient(row.base_url, row.username, decrypt_secret(row.password_ciphertext))
        directories = await client.list_directories(normalized_path)
    except Exception as exc:
        raise alist_http_exception(exc) from exc

    def directory_path(name: str) -> str:
        return f"/{name}" if normalized_path == "/" else f"{normalized_path}/{name}"

    parent_path = "/" if normalized_path == "/" else normalized_path.rsplit("/", 1)[0] or "/"
    return {
        "path": normalized_path,
        "parent_path": parent_path,
        "items": [
            {
                "name": str(item["name"]),
                "path": directory_path(str(item["name"])),
                "modified": item.get("modified"),
            }
            for item in directories
        ],
    }


@app.get("/api/admin/root-mappings")
async def get_root_mappings():
    async with StateSession() as session:
        rows = list((await session.scalars(select(ContentRootMapping).order_by(ContentRootMapping.sort_order))).all())
        return {"items": [{"id": row.id, "content_type": row.content_type, "display_name": row.display_name, "alist_path": row.alist_path, "enabled": row.enabled, "sort_order": row.sort_order} for row in rows]}


async def validate_root_mapping_path(path: str) -> str:
    normalized = normalize_path(path)
    async with StateSession() as session:
        connection = await session.get(AListConnection, 1)
    if not connection or not connection.enabled or not connection.password_ciphertext:
        raise HTTPException(409, "请先保存可用的 AList 连接和凭据")
    try:
        client = AListClient(connection.base_url, connection.username, decrypt_secret(connection.password_ciphertext))
        info = await client.get_path(normalized)
    except Exception as exc:
        raise alist_http_exception(exc) from exc
    if info.get("is_dir") is False:
        raise HTTPException(400, "根目录映射必须指向 AList 文件夹")
    return normalized


@app.post("/api/admin/root-mappings")
async def add_root_mapping(payload: RootMappingInput):
    normalized_path = await validate_root_mapping_path(payload.alist_path)
    async with StateSession() as session:
        row = ContentRootMapping(**{**payload.model_dump(), "alist_path": normalized_path})
        session.add(row)
        try:
            await session.commit()
        except Exception as exc:
            await session.rollback()
            raise HTTPException(409, "该 AList 根目录已存在") from exc
        await session.refresh(row)
        return {"id": row.id}


@app.put("/api/admin/root-mappings/{mapping_id}")
async def update_root_mapping(mapping_id: int, payload: RootMappingInput):
    normalized_path = await validate_root_mapping_path(payload.alist_path)
    async with StateSession() as session:
        row = await session.get(ContentRootMapping, mapping_id)
        if not row:
            raise HTTPException(404, "映射不存在")
        for key, value in {**payload.model_dump(), "alist_path": normalized_path}.items():
            setattr(row, key, value)
        try:
            await session.commit()
        except Exception as exc:
            await session.rollback()
            raise HTTPException(409, "该 AList 根目录已被其他映射使用") from exc
        return {"ok": True}


@app.delete("/api/admin/root-mappings/{mapping_id}")
async def delete_root_mapping(mapping_id: int):
    async with StateSession() as session:
        row = await session.get(ContentRootMapping, mapping_id)
        if not row:
            raise HTTPException(404, "映射不存在")
        await session.delete(row)
        await session.commit()
        return {"ok": True}


@app.post("/api/admin/sync", status_code=202)
async def sync(payload: SyncInput):
    global manual_sync_task
    if manual_sync_task and not manual_sync_task.done():
        return {"status": "already_running"}
    preflight = await sync_preflight("manual", payload.force)
    if preflight:
        return preflight
    manual_sync_task = asyncio.create_task(
        _run_manual_sync_in_background(payload.full, payload.force),
        name="cloudsite-manual-sync",
    )
    return {"status": "accepted", "message": "同步任务已启动"}


@app.get("/api/admin/sync/status")
async def admin_rolling_sync_status():
    return await rolling_status()


@app.post("/api/admin/sync/auto-toggle")
async def toggle_auto_sync():
    async with StateSession() as session:
        row = await session.get(SystemSetting, "automatic_sync") or SystemSetting(key="automatic_sync")
        current = row.value == "true"
        row.value = "false" if current else "true"
        session.add(row)
        await session.commit()
        return {"ok": True, "automatic_sync": not current}


@app.post("/api/admin/sync/window/run", status_code=202)
async def admin_run_rolling_window():
    global manual_sync_task
    if not await rolling_enabled():
        raise HTTPException(409, "首次完整索引尚未完成，不能进入 Rolling 1.1")
    if manual_sync_task and not manual_sync_task.done():
        return {"status": "already_running"}
    preflight = await sync_preflight("rolling", False)
    if preflight:
        return preflight
    manual_sync_task = asyncio.create_task(
        _run_manual_sync_in_background(False, False),
        name="cloudsite-rolling-window",
    )
    return {"status": "accepted", "message": "Rolling Window 已启动"}


@app.post("/api/admin/search/rebuild")
async def rebuild_public_search_index():
    await set_search_index_dirty(True)
    async with IndexSession() as session:
        folders = list((await session.scalars(select(Folder).where(Folder.status == "active"))).all())
        resources = list((await session.scalars(select(Resource).where(Resource.status == "active"))).all())
        count = await rebuild_search_index(session, folders, resources)
        await session.commit()
    await set_search_index_dirty(False)
    await log_operation("search", "rebuild", f"搜索索引重建完成：{count} 个对象")
    return {"ok": True, "indexed": count, "folders": len(folders), "resources": len(resources)}


def sync_run_dict(row: SyncRun) -> dict:
    return {
        "id": row.id,
        "sync_type": row.sync_type,
        "status": row.status,
        "folders_scanned": row.folders_scanned,
        "resources_scanned": row.resources_scanned,
        "added_count": row.added_count,
        "updated_count": row.updated_count,
        "removed_count": row.removed_count,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
        "duration_ms": row.duration_ms,
        "error_message": row.error_message,
        "current_path": row.current_path,
        "roots_total": row.roots_total,
        "roots_completed": row.roots_completed,
        "roots_failed": row.roots_failed,
    }


@app.get("/api/admin/index/summary")
async def admin_index_summary():
    async with IndexSession() as session:
        latest = await session.scalar(select(SyncRun).order_by(desc(SyncRun.id)).limit(1))
        return {
            "folders": int(await session.scalar(select(func.count()).select_from(Folder).where(Folder.status == "active")) or 0),
            "resources": int(await session.scalar(select(func.count()).select_from(Resource).where(Resource.status == "active")) or 0),
            "latest_sync": sync_run_dict(latest) if latest else None,
            "syncing": bool(latest and latest.status == "running"),
        }


@app.get("/api/admin/index/folders")
async def admin_index_folders():
    async with IndexSession() as session:
        rows = list((await session.scalars(select(Folder).where(Folder.status == "active").order_by(Folder.depth, Folder.path))).all())
        return {"items": [folder_dict(row, include_path=True) for row in rows]}


@app.get("/api/admin/index/folders/{folder_id}")
async def admin_index_folder_detail(folder_id: str):
    async with IndexSession() as session:
        row = await session.get(Folder, folder_id)
        if not row or row.status != "active":
            raise HTTPException(404, "索引目录不存在")
        resources_count = int(await session.scalar(select(func.count()).select_from(Resource).where(Resource.parent_id == row.id, Resource.status == "active")) or 0)
        return {**folder_dict(row, include_path=True), "direct_resource_count": resources_count}


@app.get("/api/admin/sync-runs")
async def admin_sync_runs(limit: int = Query(10, ge=1, le=100)):
    async with IndexSession() as session:
        rows = list((await session.scalars(select(SyncRun).order_by(desc(SyncRun.id)).limit(limit))).all())
        return {"items": [sync_run_dict(row) for row in rows]}


@app.get("/api/admin/sync-runs/{run_id}/changes")
async def admin_sync_changes(run_id: int, limit: int = Query(100, ge=1, le=500)):
    async with IndexSession() as session:
        if not await session.get(SyncRun, run_id):
            raise HTTPException(404, "同步记录不存在")
        rows = list((await session.scalars(select(SyncChange).where(SyncChange.sync_run_id == run_id).order_by(desc(SyncChange.id)).limit(limit))).all())
        return {"items": [{"id": row.id, "object_type": row.object_type, "object_id": row.object_id, "change_type": row.change_type, "old_path": row.old_path, "new_path": row.new_path, "created_at": row.created_at} for row in rows]}


@app.get("/api/admin/collections")
async def admin_collections():
    async with StateSession() as state, IndexSession() as index:
        rows = list((await state.scalars(select(Collection).order_by(Collection.sort_order, desc(Collection.updated_at)))).all())
        return {"items": [await collection_dict(state, index, row) for row in rows]}


@app.get("/api/admin/collections/{collection_id}")
async def admin_collection_detail(collection_id: int):
    async with StateSession() as state, IndexSession() as index:
        row = await state.get(Collection, collection_id)
        if not row:
            raise HTTPException(404, "合集不存在")
        items = list((await state.scalars(select(CollectionItem).where(CollectionItem.collection_id == collection_id).order_by(CollectionItem.sort_order, CollectionItem.id))).all())
        resource_ids = [item.resource_id for item in items]
        resources_by_id = {}
        if resource_ids:
            resources_by_id = {resource.id: resource for resource in (await index.scalars(select(Resource).where(Resource.id.in_(resource_ids)))).all()}
        payload = {
            "id": row.id,
            "name": row.name,
            "description": row.description,
            "cover": row.cover,
            "status": row.status,
            "visible_on_home": row.visible_on_home,
            "sort_order": row.sort_order,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "items": [],
        }
        for item in items:
            resource = resources_by_id.get(item.resource_id)
            if resource and resource.status == "active":
                payload["items"].append({"resource_id": item.resource_id, "name": resource.name, "content_type": resource.content_type, "extension": resource.extension, "size": resource.size, "active": True})
            else:
                payload["items"].append({"resource_id": item.resource_id, "name": None, "content_type": "", "extension": "", "size": 0, "active": False})
        return payload


@app.post("/api/admin/collections")
async def create_collection(payload: CollectionInput):
    async with StateSession() as session:
        row = Collection(**payload.model_dump())
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return {"id": row.id}


@app.put("/api/admin/collections/{collection_id}")
async def update_collection(collection_id: int, payload: CollectionInput):
    async with StateSession() as session:
        row = await session.get(Collection, collection_id)
        if not row:
            raise HTTPException(404, "合集不存在")
        for key, value in payload.model_dump().items():
            setattr(row, key, value)
        await session.commit()
        return {"ok": True}


@app.put("/api/admin/collections/{collection_id}/items")
async def set_collection_items(collection_id: int, payload: CollectionItemsInput):
    async with StateSession() as state, IndexSession() as index:
        if not await state.get(Collection, collection_id):
            raise HTTPException(404, "合集不存在")
        resource_ids = list(dict.fromkeys(payload.resource_ids))
        if resource_ids:
            existing = set((await index.scalars(select(Resource.id).where(Resource.id.in_(resource_ids), Resource.status == "active"))).all())
            missing = [resource_id for resource_id in resource_ids if resource_id not in existing]
            if missing:
                raise HTTPException(400, f"资源不存在：{', '.join(missing[:5])}")
        await state.execute(delete(CollectionItem).where(CollectionItem.collection_id == collection_id))
        state.add_all([CollectionItem(collection_id=collection_id, resource_id=resource_id, sort_order=position) for position, resource_id in enumerate(resource_ids)])
        await state.commit()
        return {"ok": True, "item_count": len(resource_ids)}


@app.delete("/api/admin/collections/{collection_id}")
async def delete_collection(collection_id: int):
    async with StateSession() as session:
        row = await session.get(Collection, collection_id)
        if not row:
            raise HTTPException(404, "合集不存在")
        await session.delete(row)
        await session.commit()
        return {"ok": True}


async def owned_share(state, token: str, user_id: int) -> Share:
    row = await state.scalar(
        select(Share).where(Share.token == token, Share.creator_user_id == user_id)
    )
    if not row:
        raise HTTPException(404, {"code": "SHARE_NOT_FOUND", "message": "分享不存在"})
    return row


@app.get("/api/my/shares")
async def my_shares(request: Request):
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


@app.post("/api/my/shares")
async def create_my_share(payload: ShareInput, request: Request):
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


@app.patch("/api/my/shares/{token}")
async def update_my_share(token: str, payload: ShareUpdate, request: Request):
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


@app.delete("/api/my/shares/{token}")
async def delete_my_share(token: str, request: Request):
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


@app.get("/api/admin/shares")
async def admin_shares():
    async with StateSession() as state, IndexSession() as index:
        rows = list((await state.scalars(select(Share).order_by(desc(Share.created_at)))).all())
        resource_ids = [row.object_id for row in rows if row.object_type == "resource"]
        folder_ids = [row.object_id for row in rows if row.object_type == "folder"]
        collection_ids = [int(row.object_id) for row in rows if row.object_type == "collection" and row.object_id.isdigit()]
        creator_ids = {row.creator_user_id for row in rows if row.creator_user_id is not None}
        names: dict[str, str] = {}
        creators = {
            row.id: row.username
            for row in (
                await state.scalars(select(User).where(User.id.in_(creator_ids)))
            ).all()
        } if creator_ids else {}
        if resource_ids:
            names.update({row.id: row.name for row in (await index.scalars(select(Resource).where(Resource.id.in_(resource_ids)))).all()})
        if folder_ids:
            names.update({row.id: row.name for row in (await index.scalars(select(Folder).where(Folder.id.in_(folder_ids)))).all()})
        if collection_ids:
            names.update({str(row.id): row.name for row in (await state.scalars(select(Collection).where(Collection.id.in_(collection_ids)))).all()})
        items = []
        for row in rows:
            target_valid = await target_valid_for_share(state, index, row)
            status = share_status(row, target_valid)
            items.append(
                share_dict(row)
                | {
                    "expired": status == "expired",
                    "status": status,
                    "target_name": names.get(row.object_id),
                    "creator_username": creators.get(row.creator_user_id),
                }
            )
        return {"items": items}


@app.post("/api/admin/shares")
async def create_share(payload: ShareInput):
    async with StateSession() as state, IndexSession() as index:
        created = await create_share_row(state, index, payload)
        await state.commit()
        return share_dict(created.share) | {"code": created.code}


@app.patch("/api/admin/shares/{token}")
async def update_share(token: str, payload: ShareUpdate):
    async with StateSession() as session:
        row = await session.get(Share, token)
        if not row:
            raise HTTPException(404, "分享不存在")
        if payload.action == "cancel" or payload.enabled is False:
            await cancel_share_row(session, row)
        elif payload.action == "restore" or payload.enabled is True:
            await restore_share(session, row, payload.duration)
        elif payload.action in {"reset_code", "upgrade"}:
            code = await reset_share_code(session, row)
            await session.commit()
            return share_dict(row) | {"code": code}
        if payload.duration:
            await update_share_duration(session, row, payload.duration)
        await session.commit()
        return share_dict(row)


@app.delete("/api/admin/shares/{token}")
async def delete_share(token: str):
    async with StateSession() as session:
        row = await session.get(Share, token)
        if not row:
            raise HTTPException(404, "分享不存在")
        session.add(OperationLog(level="INFO", module="share", action="share_deleted", message=f"删除分享 {token}"))
        await session.delete(row)
        await session.commit()
        return {"ok": True}


@app.get("/api/admin/system")
async def get_system():
    async with StateSession() as state, IndexSession() as index:
        values = await get_system_values(state)
        values.update({
            "version": __version__,
            "database": "SQLite 3",
            "timezone": "Asia/Shanghai",
            "resources": int(await index.scalar(select(func.count()).select_from(Resource).where(Resource.status == "active")) or 0),
            "folders": int(await index.scalar(select(func.count()).select_from(Folder).where(Folder.status == "active")) or 0),
            "operation_logs": int(await state.scalar(select(func.count()).select_from(OperationLog)) or 0),
        })
    values["provider"] = await provider_info()
    return values


@app.put("/api/admin/system")
async def save_system(payload: SystemInput):
    async with StateSession() as session:
        for key, value in payload.model_dump().items():
            row = await session.get(SystemSetting, key) or SystemSetting(key=key)
            row.value = str(value).lower() if isinstance(value, bool) else str(value)
            session.add(row)
        await session.commit()
        return {"ok": True}


@app.get("/api/admin/site")
async def get_site():
    async with StateSession() as session:
        row = await session.get(SiteSettings, 1) or SiteSettings(id=1)
        return site_settings_dict(row)


@app.put("/api/admin/site")
async def save_site(payload: SiteSettingsUpdate, request: Request):
    validate_request_origin(request)
    async with StateSession() as session:
        row = await session.get(SiteSettings, 1) or SiteSettings(id=1)
        changed: list[str] = []
        for key, value in payload.model_dump(exclude_unset=True, exclude_none=True).items():
            if getattr(row, key) != value:
                setattr(row, key, value)
                changed.append(key)
        session.add(row)
        session.add(
            OperationLog(
                level="INFO",
                module="site",
                action="site_settings_updated",
                message=f"更新站点设置：{', '.join(changed) or '无变化'}",
            )
        )
        await session.commit()
        return {"ok": True, **site_settings_dict(row)}


@app.post("/api/admin/site/share-image")
async def upload_share_page_image(request: Request, file: UploadFile = File(...)):
    validate_request_origin(request)
    data = await file.read(SHARE_IMAGE_MAX_BYTES + 1)
    await file.close()
    if not data:
        raise HTTPException(400, {"code": "SHARE_IMAGE_EMPTY", "message": "请选择图片文件"})
    if len(data) > SHARE_IMAGE_MAX_BYTES:
        raise HTTPException(413, {"code": "SHARE_IMAGE_TOO_LARGE", "message": "图片不能超过 8MB"})
    try:
        new_name = save_share_image(data)
    except ValueError as exc:
        raise HTTPException(400, {"code": "SHARE_IMAGE_INVALID", "message": str(exc)}) from exc
    old_name = ""
    try:
        async with StateSession() as session:
            row = await session.get(SiteSettings, 1) or SiteSettings(id=1)
            old_name = row.share_image_name or ""
            row.share_image_name = new_name
            session.add(row)
            await session.commit()
    except Exception:
        remove_share_image(new_name)
        raise
    if old_name and old_name != new_name:
        remove_share_image(old_name)
    return {"ok": True, "share_image_url": "/api/public/share-page/image"}


@app.delete("/api/admin/site/share-image")
async def delete_share_page_image(request: Request):
    validate_request_origin(request)
    async with StateSession() as session:
        row = await session.get(SiteSettings, 1)
        old_name = row.share_image_name if row else ""
        if row:
            row.share_image_name = ""
            await session.commit()
    if old_name:
        remove_share_image(old_name)
    return {"ok": True}
