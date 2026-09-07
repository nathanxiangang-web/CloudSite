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



from .routers.admin.auth import router as admin_auth_router
app.include_router(admin_auth_router)
from .routers.admin.setup import router as admin_setup_router
app.include_router(admin_setup_router)
from .routers.admin.overview import router as admin_overview_router
app.include_router(admin_overview_router)
from .routers.admin.diagnostics import router as admin_diagnostics_router, download_diagnostic_dict
app.include_router(admin_diagnostics_router)
from .routers.admin.identities import router as admin_identities_router
app.include_router(admin_identities_router)
from .routers.admin.alist import router as admin_alist_router
app.include_router(admin_alist_router)
from .routers.admin.content_roots import router as admin_content_roots_router
app.include_router(admin_content_roots_router)
from .routers.admin.sync import router as admin_sync_router, sync
app.include_router(admin_sync_router)
from .routers.admin.search import router as admin_search_router
app.include_router(admin_search_router)
from .routers.admin.index import router as admin_index_router, sync_run_dict
app.include_router(admin_index_router)
from .routers.admin.collections import router as admin_collections_router
app.include_router(admin_collections_router)
from .routers.admin.shares import router as admin_shares_router
app.include_router(admin_shares_router)
from .routers.admin.system import router as admin_system_router
app.include_router(admin_system_router)
from .routers.admin.site import router as admin_site_router, site_settings_dict
app.include_router(admin_site_router)
from .routers.admin.submissions import router as admin_submissions_router
app.include_router(admin_submissions_router)
from .routers.admin.notifications import router as admin_notifications_router
app.include_router(admin_notifications_router)


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



from .services.downloads import _download_event
