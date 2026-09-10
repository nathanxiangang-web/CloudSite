"""CloudSite API 应用入口。

本模块仅负责组装 FastAPI 应用：注册生命周期、中间件、异常处理器与路由。
后台调度、中间件与异常处理实现已迁移至 ``tasks/`` 与 ``infrastructure/`` 包，
但为兼容测试 monkeypatch 与路由懒加载，此处保留必要的 re-export。
"""
import asyncio
import logging
import time

from fastapi import FastAPI

from . import __version__
from .alist import AListClient
from .database import IndexSession, StateSession, init_databases, validate_database_files
from .download import resolve_download_entry
from .download_rate_limit import DOWNLOAD_RATE_CLEANUP_SECONDS, check_download_rate, cleanup_download_rate_limits
from .identity import backup_stable_id_databases, migrate_stable_resource_ids
from .indexer import (
    automatic_sync_due,
    log_operation,
    recover_interrupted_sync_runs,
    run_sync,
    sync_preflight,
)
from .infrastructure.security import (
    create_session_token,
    validate_production_secrets,
    verify_session_token,
)
from .search import recover_search_index_if_dirty
from .sessions import SESSION_CLEANUP_SECONDS, cleanup_expired_user_sessions
from .shares.service import cleanup_share_verify_attempts, cleanup_terminal_shares
from .sync.rolling import (
    migrate_existing_index_to_rolling,
    prepare_index_recovery,
    recover_rolling_state,
    resolve_rolling_mode,
    rolling_enabled,
    run_due_rolling_window,
)
from .tasks.scheduler import SYNC_INTERVAL_OPTIONS, _run_cleanup_job, get_system_values, scheduler_loop
from .tasks.sync import _run_manual_sync_in_background, _safe_startup_sync
from .infrastructure.lifespan import lifespan
from .infrastructure.middleware import register_middlewares
from .infrastructure.exception_handlers import register_exception_handlers

logger = logging.getLogger(__name__)

# 全局任务句柄：lifespan 创建/取消，admin/sync 路由读写 manual_sync_task。
scheduler_task: asyncio.Task | None = None
manual_sync_task: asyncio.Task | None = None

# 清理计数器：scheduler_loop 读写，测试 monkeypatch。
_last_rate_limit_cleanup_at = 0.0
_last_session_cleanup_at = 0.0
_last_share_cleanup_at = 0.0

# 常量：中间件与 scheduler 引用，测试 monkeypatch。
SESSION_COOKIE = "cloudsite_session"
SHARE_CLEANUP_SECONDS = 3600

app = FastAPI(title="CloudSite API", version=__version__, lifespan=lifespan)

register_middlewares(app)
register_exception_handlers(app)

# 路由注册
from .auth import router as auth_router
from .users import router as users_router
from .userdata import router as userdata_router
from .site import router as site_router
from .routers.health import router as health_router
from .routers.home import (
    router as home_router,
    _home_cache,
    _storage_info_cache,
    _alist_connection_cache,
)
from .routers.resources import router as resources_router
from .routers.previews import router as previews_router
from .routers.search import router as search_router
from .routers.collections import router as collections_router
from .routers.shares import router as shares_router
from .routers.downloads import router as downloads_router
from .routers.submissions import router as submissions_router
from .routers.notifications import router as notifications_router
from .routers.catalog import router as catalog_router
from .routers.catalog_follow import router as catalog_follow_router

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(userdata_router)
app.include_router(site_router)
app.include_router(health_router)
app.include_router(home_router)
app.include_router(resources_router)
app.include_router(previews_router)
app.include_router(search_router)
app.include_router(collections_router)
app.include_router(shares_router)
app.include_router(downloads_router)
app.include_router(submissions_router)
app.include_router(notifications_router)
app.include_router(catalog_router)
app.include_router(catalog_follow_router)

from .routers.admin.auth import router as admin_auth_router
from .routers.admin.setup import router as admin_setup_router
from .routers.admin.overview import router as admin_overview_router
from .routers.admin.diagnostics import router as admin_diagnostics_router, download_diagnostic_dict
from .routers.admin.identities import router as admin_identities_router
from .routers.admin.alist import router as admin_alist_router
from .routers.admin.content_roots import router as admin_content_roots_router
from .routers.admin.sync import router as admin_sync_router, sync
from .routers.admin.search import router as admin_search_router
from .routers.admin.index import router as admin_index_router, sync_run_dict
from .routers.admin.collections import router as admin_collections_router
from .routers.admin.shares import router as admin_shares_router
from .routers.admin.system import router as admin_system_router
from .routers.admin.site import router as admin_site_router, site_settings_dict
from .routers.admin.submissions import router as admin_submissions_router
from .routers.admin.notifications import router as admin_notifications_router
from .routers.admin.catalog import router as admin_catalog_router
from .routers.admin.catalog_metadata import router as admin_catalog_metadata_router
from .routers.admin.automation import router as admin_automation_router

app.include_router(admin_auth_router)
app.include_router(admin_setup_router)
app.include_router(admin_overview_router)
app.include_router(admin_diagnostics_router)
app.include_router(admin_identities_router)
app.include_router(admin_alist_router)
app.include_router(admin_content_roots_router)
app.include_router(admin_sync_router)
app.include_router(admin_search_router)
app.include_router(admin_index_router)
app.include_router(admin_collections_router)
app.include_router(admin_shares_router)
app.include_router(admin_system_router)
app.include_router(admin_site_router)
app.include_router(admin_submissions_router)
app.include_router(admin_notifications_router)
app.include_router(admin_catalog_router)
app.include_router(admin_catalog_metadata_router)
app.include_router(admin_automation_router)

# 公开 DTO 与服务函数 re-export：路由懒加载与测试直接引用。
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
from .schemas import SyncInput
