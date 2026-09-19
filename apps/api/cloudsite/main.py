from .site import admin_site_settings_payload as site_settings_dict
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
from .indexer import log_operation, recover_interrupted_sync_runs
from .infrastructure.security import (
    create_session_token,
    validate_production_secrets,
    verify_session_token,
)
from .search import recover_search_index_if_dirty
from .sessions import SESSION_CLEANUP_SECONDS, cleanup_expired_user_sessions
from .shares.service import cleanup_share_verify_attempts, cleanup_terminal_shares
from .tasks.scheduler import SYNC_INTERVAL_OPTIONS, _run_cleanup_job, get_system_values, scheduler_loop
from .tasks.sync import _run_manual_sync_in_background, _safe_startup_sync
from .infrastructure.lifespan import lifespan
from .infrastructure.middleware import register_middlewares
from .infrastructure.exception_handlers import register_exception_handlers
from .infrastructure.composition import compose_app, create_app_shell

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

app = create_app_shell()
_registry, users_router = compose_app(app)

# 兼容 re-export：历史测试与懒加载代码仍直接从 cloudsite.main 读取这些符号。
from .routers.home import (
    _home_cache,
    _storage_info_cache,
    _alist_connection_cache,
)
from .routers.admin.diagnostics import download_diagnostic_dict
from .routers.admin.sync import sync
from .routers.admin.index import sync_run_dict
from .plugins import PluginRegistry


# 公开 DTO 与服务函数 re-export：路由懒加载与测试直接引用。
from .services.resources import (
    breadcrumbs_batch,
    breadcrumbs_for,
    breadcrumbs_for_folder,
    folder_dict,
    resource_dict,
)
from .modules.collections.contracts.public import collection_view as collection_dict
from .services.shares import (
    build_share_target_payload,
    resolve_share_download_resource,
    share_dict,
    share_is_expired,
)
from .services.submissions import submission_dict, validate_optional_http_url
from .modules.notifications.contracts.public import notification_dict
from .modules.delivery.contracts.public import _download_event
from .schemas import SyncInput
