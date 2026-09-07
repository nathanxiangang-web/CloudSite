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
from urllib.parse import urlencode, urlparse

from fastapi import FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy import and_, delete, desc, func, or_, select, text

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
    Notification,
    OperationLog,
    Resource,
    ResourceIdentity,
    ResourceIdentityCandidate,
    ResourceIdentityHistory,
    Share,
    SiteSettings,
    Submission,
    SyncRun,
    SystemSetting,
    User,
    utcnow,
)
from .office import OFFICE_CONTENT_TYPES, OfficePreviewError, ensure_preview_cached, office_cache_filename, office_content_type
from .preview import PreviewError, load_text_preview, preview_capability, resolve_preview_url, validate_preview_ticket
from .providers.service import provider_info
from .request_context import request_is_https
from .admin_auth import (
    AdminAuthMode,
    get_setup_completed,
    ensure_setup_compatible,
    is_public_admin_endpoint,
    should_block_admin_request,
    verify_setup_token,
)
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
    SubmissionInput,
    SubmissionReviewInput,
    NotificationInput,
    NotificationUpdate,
    PathSyncInput,
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
    enabled_root_ids,
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
_last_rate_limit_cleanup_at = 0.0
_last_session_cleanup_at = 0.0
_last_share_cleanup_at = 0.0
SHARE_CLEANUP_SECONDS = 3600
SYNC_INTERVAL_OPTIONS = {180, 360, 720, 1440}
logger = logging.getLogger(__name__)


from .infrastructure.security import (
    ADMIN_SESSION_MAX_AGE_SECONDS,
    create_session_token,
    verify_session_token,
)


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


_INSECURE_SECRET_VALUES = {
    "cloudsite-development-key-change-me",
    "replace-with-a-long-random-secret",
    "change-me",
}


def validate_production_secrets() -> None:
    if settings.allow_insecure_dev_key:
        return
    key = settings.secret_key
    if not key or key in _INSECURE_SECRET_VALUES:
        raise RuntimeError(
            "CLOUDSITE_SECRET_KEY 未设置或使用了公开占位值，拒绝启动。"
            "请生成随机密钥：python -c \"import secrets; print(secrets.token_urlsafe(48))\""
        )
    if len(key) < 32:
        raise RuntimeError("CLOUDSITE_SECRET_KEY 长度不足 32 字符，拒绝启动。")
    if not settings.master_key:
        logger.warning("CLOUDSITE_MASTER_KEY 未设置，凭据加密将回退到 SECRET_KEY。生产环境建议显式设置独立 MASTER_KEY。")


@asynccontextmanager
async def lifespan(_: FastAPI):
    global scheduler_task, manual_sync_task
    validate_production_secrets()
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
        await ensure_setup_compatible(session)
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
from .routers.health import router as health_router
app.include_router(health_router)
from .routers.home import (
    router as home_router,
    _home_cache,
    _storage_info_cache,
    _alist_connection_cache,
)
app.include_router(home_router)
from .routers.resources import router as resources_router
app.include_router(resources_router)
from .routers.previews import router as previews_router
app.include_router(previews_router)
from .routers.search import router as search_router
app.include_router(search_router)
from .routers.collections import router as collections_router
app.include_router(collections_router)
from .routers.shares import router as shares_router
app.include_router(shares_router)
from .routers.downloads import router as downloads_router
app.include_router(downloads_router)
from .routers.submissions import router as submissions_router
app.include_router(submissions_router)
from .routers.notifications import router as notifications_router
app.include_router(notifications_router)


@app.middleware("http")
async def admin_session_middleware(request: Request, call_next):
    path = request.url.path
    if request.method == "OPTIONS":
        return await call_next(request)

    if path.startswith("/api/admin"):
        # M4: 精确公开端点放行（写操作仍做同源校验）
        if is_public_admin_endpoint(request.method, path):
            if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                try:
                    validate_request_origin(request)
                except Exception:
                    return JSONResponse(
                        {"detail": {"code": "ORIGIN_FORBIDDEN", "message": "请求来源校验失败"}},
                        status_code=403,
                    )
            return await call_next(request)
        # M4: 统一失败关闭判定
        async with StateSession() as session:
            setup_completed = await get_setup_completed(session)
        admin_authenticated = verify_session_token(request.cookies.get(SESSION_COOKIE))
        block, error_code = should_block_admin_request(
            method=request.method,
            path=path,
            setup_completed=setup_completed,
            admin_cookie_valid=admin_authenticated,
        )
        if block:
            if error_code == "SETUP_REQUIRED":
                return JSONResponse(
                    {"detail": {"code": "SETUP_REQUIRED", "message": "站点尚未完成初始化"}},
                    status_code=409,
                )
            return JSONResponse(
                {"detail": {"code": "ADMIN_REQUIRED", "message": "请先登录管理后台"}},
                status_code=403,
            )
        # M6: 后台写操作同源校验
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            try:
                validate_request_origin(request)
            except Exception:
                return JSONResponse(
                    {"detail": {"code": "ORIGIN_FORBIDDEN", "message": "请求来源校验失败"}},
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



@app.get("/api/admin/auth/status")
async def admin_auth_status(request: Request):
    async with StateSession() as session:
        setup_completed = await get_setup_completed(session)
    admin_cookie_valid = verify_session_token(request.cookies.get(SESSION_COOKIE))
    if not setup_completed:
        mode = AdminAuthMode.SETUP_REQUIRED
    elif not admin_cookie_valid:
        mode = AdminAuthMode.LOGIN_REQUIRED
    else:
        mode = AdminAuthMode.AUTHENTICATED
    return {
        "mode": mode,
        "authenticated": mode == AdminAuthMode.AUTHENTICATED,
        "auth_required": True,
    }


@app.post("/api/admin/auth/login")
async def admin_login(payload: AdminLoginInput, request: Request, response: Response):
    async with StateSession() as session:
        setup_completed = await get_setup_completed(session)
        connection = await session.get(AListConnection, 1)
    if not setup_completed:
        raise HTTPException(409, {"code": "SETUP_REQUIRED", "message": "站点尚未完成初始化"})
    if not connection:
        raise HTTPException(409, {"code": "SETUP_REQUIRED", "message": "尚未配置 AList，请先完成初始化"})
    try:
        await AListClient(connection.base_url, payload.username, payload.password).test()
    except Exception as exc:
        raise HTTPException(401, "账号或密码错误") from exc
    response.set_cookie(
        SESSION_COOKIE,
        create_session_token(payload.username),
        max_age=ADMIN_SESSION_MAX_AGE_SECONDS,
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


@app.get("/api/admin/setup/status")
async def admin_setup_status():
    async with StateSession() as session:
        setup_completed = await get_setup_completed(session)
    return {
        "setup_required": not setup_completed,
        "setup_available": bool(settings.setup_token),
    }


@app.post("/api/admin/setup/alist")
async def admin_setup_alist(payload: AListInput, request: Request):
    # M3: 一次性初始化，固定处理顺序
    # 1. 同源校验（中间件已对公开写端点执行，这里二次确认）
    try:
        validate_request_origin(request)
    except Exception:
        raise HTTPException(403, {"code": "ORIGIN_FORBIDDEN", "message": "请求来源校验失败"})
    # 2. 检查是否仍为 setup_required
    async with StateSession() as session:
        setup_completed = await get_setup_completed(session)
        if setup_completed:
            raise HTTPException(409, {"code": "SETUP_ALREADY_COMPLETED", "message": "站点已完成初始化"})
        # 3. 检查初始化令牌
        if not settings.setup_token:
            raise HTTPException(503, {"code": "SETUP_UNAVAILABLE", "message": "服务器未配置初始化令牌"})
        provided_token = request.headers.get("X-CloudSite-Setup-Token", "")
        if not verify_setup_token(provided_token, settings.setup_token):
            raise HTTPException(403, {"code": "SETUP_FORBIDDEN", "message": "初始化令牌错误"})
        # 4. 校验请求字段（AListInput 已由 Pydantic 完成）
        # 5. 使用提交的配置测试 AList 登录
        try:
            result = await AListClient(payload.base_url, payload.username, payload.password).test()
        except Exception as exc:
            raise HTTPException(400, {"code": "ALIST_TEST_FAILED", "message": f"AList 验证失败：{str(exc)[:200]}"}) from exc
        # 6. 测试成功后保存 AList 配置 + 写入 setup_completed（同一事务）
        row = await session.get(AListConnection, 1) or AListConnection(id=1)
        row.base_url = payload.base_url.rstrip("/")
        row.base_path = result.get("base_path") or "/"
        row.username = payload.username
        row.password_ciphertext = encrypt_secret(payload.password) if payload.remember_credentials else ""
        row.remember_credentials = payload.remember_credentials
        row.enabled = True
        row.last_test_status = "success"
        row.last_test_message = "初始化时 AList 连接验证成功"
        row.last_test_at = utcnow()
        session.add(row)
        session.add(SystemSetting(key="setup_completed", value="true", value_type="string"))
        session.add(OperationLog(module="setup", action="alist_init", message="一次性初始化完成，AList 配置已保存"))
        await session.commit()
    # 7. 清理 AList 配置缓存
    _alist_connection_cache["data"] = None
    _alist_connection_cache["fetched_at"] = 0.0
    return {"setup_completed": True, "next": "/admin/login"}


from .services.resources import (
    breadcrumbs_batch,
    breadcrumbs_for,
    breadcrumbs_for_folder,
    folder_dict,
    resource_dict,
)
from .services.collections import collection_dict
from .services.shares import (
    build_share_target_payload,
    resolve_share_download_resource,
    share_dict,
    share_is_expired,
)
from .services.submissions import submission_dict, validate_optional_http_url
from .services.notifications import notification_dict


def site_settings_dict(row: SiteSettings) -> dict:
    return {
        **public_site_settings(row),
        "share_image_url": "/api/public/share-page/image" if row.share_image_name else "",
    }


from .services.downloads import _download_event


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



@app.post("/api/admin/sync/path", status_code=202)
async def sync_path(payload: PathSyncInput):
    from .sync.path_sync import ManualSyncOrchestrator, validate_paths_under_roots
    async with StateSession() as state_session:
        roots = list((await state_session.scalars(select(ContentRootMapping).where(ContentRootMapping.enabled == True))).all())
    accepted, rejected = validate_paths_under_roots(payload.paths, roots)
    if not accepted:
        return {"status": "invalid_path", "rejected_paths": rejected}
    orchestrator = ManualSyncOrchestrator.instance()
    if not orchestrator.try_reserve():
        return {"status": "already_running"}
    force_refresh_paths = set(accepted) if payload.force_refresh else set()
    asyncio.create_task(orchestrator.start(accepted, force_refresh_paths), name="cloudsite-path-sync")
    await log_operation("sync", "path_sync_triggered", f"手动同步路径: {accepted}, 强制刷新: {payload.force_refresh}")
    return {"status": "accepted", "accepted_paths": accepted, "rejected_paths": rejected}


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
        engine_version_row = await state.get(SystemSetting, "sync_engine_version")
        initial_index_row = await state.get(SystemSetting, "initial_index_completed_at")
        values.update({
            "version": __version__,
            "database": "SQLite 3",
            "timezone": "Asia/Shanghai",
            "resources": int(await index.scalar(select(func.count()).select_from(Resource).where(Resource.status == "active")) or 0),
            "folders": int(await index.scalar(select(func.count()).select_from(Folder).where(Folder.status == "active")) or 0),
            "operation_logs": int(await state.scalar(select(func.count()).select_from(OperationLog)) or 0),
            "sync_engine_version": engine_version_row.value if engine_version_row else "1.0",
            "initial_index_completed_at": initial_index_row.value if initial_index_row else None,
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

@app.get("/api/admin/submissions")
async def admin_submissions(status: str | None = None):
    async with StateSession() as state:
        query = select(Submission).order_by(desc(Submission.created_at))
        if status:
            query = query.where(Submission.status == status)
        rows = list((await state.scalars(query)).all())
        user_ids = {row.user_id for row in rows}
        usernames = {u.id: u.username for u in (await state.scalars(select(User).where(User.id.in_(user_ids)))).all()} if user_ids else {}
        return {"items": [submission_dict(row, usernames.get(row.user_id, "")) for row in rows]}


@app.get("/api/admin/submissions/{submission_id}")
async def admin_submission_detail(submission_id: int):
    async with StateSession() as state:
        row = await state.get(Submission, submission_id)
        if not row:
            raise HTTPException(404, "投稿不存在")
        user = await state.get(User, row.user_id)
        return submission_dict(row, user.username if user else "")


@app.patch("/api/admin/submissions/{submission_id}")
async def review_submission(submission_id: int, payload: SubmissionReviewInput):
    async with StateSession() as state:
        row = await state.get(Submission, submission_id)
        if not row:
            raise HTTPException(404, "投稿不存在")
        action_map = {"approve": "approved", "reject": "rejected", "publish": "published"}
        row.status = action_map[payload.action]
        row.admin_note = payload.admin_note
        row.reviewed_at = utcnow()
        connection = await state.get(AListConnection, 1)
        row.reviewed_by = connection.username if connection else "admin"
        state.add(OperationLog(level="INFO", module="submission", action=f"submission_{payload.action}", message=f"投稿 #{row.id} {row.resource_name} -> {row.status}"))
        notify_title_map = {"approve": "投稿审核通过", "reject": "投稿已被拒绝", "publish": "投稿已发布"}
        notify_level_map = {"approve": "success", "reject": "warning", "publish": "success"}
        notify_body = f"你提交的《{row.resource_name}》已{('通过审核' if payload.action == 'approve' else '被拒绝' if payload.action == 'reject' else '发布')}."
        if payload.admin_note:
            notify_body += f"\n审核备注：{payload.admin_note}"
        state.add(Notification(
            user_id=row.user_id,
            title=notify_title_map[payload.action],
            body=notify_body,
            level=notify_level_map[payload.action],
            source="submission",
        ))
        await state.commit()
        await state.refresh(row)
        user = await state.get(User, row.user_id)
        return submission_dict(row, user.username if user else "")


@app.delete("/api/admin/submissions/{submission_id}")
async def delete_submission(submission_id: int):
    async with StateSession() as state:
        row = await state.get(Submission, submission_id)
        if not row:
            raise HTTPException(404, "投稿不存在")
        if row.status != "rejected":
            raise HTTPException(409, "仅已拒绝的投稿可以删除")
        state.add(OperationLog(level="INFO", module="submission", action="submission_deleted", message=f"删除投稿 #{row.id} {row.resource_name}（提交者 user_id={row.user_id}）"))
        await state.delete(row)
        await state.commit()
        return {"ok": True}

@app.get("/api/admin/notifications")
async def admin_notifications():
    async with StateSession() as state:
        rows = list((await state.scalars(select(Notification).order_by(desc(Notification.created_at)))).all())
        await state.commit()
        return {"items": [notification_dict(row) for row in rows]}


@app.post("/api/admin/notifications")
async def create_notification(payload: NotificationInput):
    async with StateSession() as state:
        row = Notification(
            title=payload.title,
            body=payload.body,
            level=payload.level,
            pinned=payload.pinned,
            enabled=payload.enabled,
            source="manual",
            expires_at=payload.expires_at,
        )
        state.add(row)
        state.add(OperationLog(level="INFO", module="notification", action="notification_created", message=f"新建通知 {payload.title}"))
        await state.commit()
        await state.refresh(row)
        return notification_dict(row)


@app.patch("/api/admin/notifications/{notification_id}")
async def update_notification(notification_id: int, payload: NotificationUpdate):
    async with StateSession() as state:
        row = await state.get(Notification, notification_id)
        if not row:
            raise HTTPException(404, "通知不存在")
        provided = payload.model_fields_set
        for field in ("title", "body", "level", "pinned", "expires_at"):
            if field in provided:
                setattr(row, field, getattr(payload, field))
        if "enabled" in provided:
            was_enabled = row.enabled
            row.enabled = payload.enabled
            if not was_enabled and payload.enabled:
                row.published_at = utcnow()
        state.add(OperationLog(level="INFO", module="notification", action="notification_updated", message=f"更新通知 #{row.id} {row.title}"))
        await state.commit()
        await state.refresh(row)
        return notification_dict(row)


@app.delete("/api/admin/notifications/{notification_id}")
async def delete_notification(notification_id: int):
    async with StateSession() as state:
        row = await state.get(Notification, notification_id)
        if not row:
            raise HTTPException(404, "通知不存在")
        state.add(OperationLog(level="INFO", module="notification", action="notification_deleted", message=f"删除通知 #{row.id} {row.title}"))
        await state.delete(row)
        await state.commit()
        return {"ok": True}


