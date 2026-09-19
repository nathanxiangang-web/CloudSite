from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from .database import IndexBase, StateBase
from .modules.identity.infrastructure.models import (
    FolderIdentity,
    FolderIdentityHistory,
    ResourceIdentity,
    ResourceIdentityCandidate,
    ResourceIdentityHistory,
)
from .modules.resources.infrastructure.models import DownloadRateLimit, Folder, Resource
from .modules.providers.infrastructure.models import (
    AListConnection,
    ContentRootMapping,
    ProviderSyncState,
)
from .modules.delivery.infrastructure.models import (
    DownloadDiagnostic,
    DownloadEvent,
)
from .modules.notifications.infrastructure.models import Notification
from .modules.catalog.infrastructure.models import (
    CatalogAsset,
    CatalogEntry,
    CatalogFavorite,
    CatalogLocation,
    CatalogRelation,
    CatalogRelease,
    CatalogReleaseNotification,
    CatalogRevision,
    CatalogSearchOutbox,
    CatalogSubscription,
    CatalogTag,
    CatalogTagAssignment,
)
from .modules.automation.infrastructure.models import ParserCandidateTask


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SiteSettings(StateBase):
    __tablename__ = "site_settings"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    site_name: Mapped[str] = mapped_column(String(100), default="CloudSite")
    home_title: Mapped[str] = mapped_column(String(200), default="把网盘变成好看的资源网站")
    description: Mapped[str] = mapped_column(String(500), default="软件、图库、视频、教程和文件，集中整理，轻松搜索，便捷分享")
    hero_subtitle: Mapped[str] = mapped_column(String(200), default="")
    footer_text: Mapped[str] = mapped_column(String(300), default="")
    submission_email: Mapped[str] = mapped_column(String(200), default="nathxo@outlook.com")
    github_url: Mapped[str] = mapped_column(String(300), default="")
    registration_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    default_share_duration: Mapped[str] = mapped_column(String(20), default="24h")
    share_image_name: Mapped[str] = mapped_column(String(255), default="")
    recent_limit: Mapped[int] = mapped_column(Integer, default=6)
    popular_limit: Mapped[int] = mapped_column(Integer, default=6)
    collection_limit: Mapped[int] = mapped_column(Integer, default=4)
    popular_strategy: Mapped[str] = mapped_column(String(20), default="recent", server_default="recent")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SystemSetting(StateBase):
    __tablename__ = "system_settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    value_type: Mapped[str] = mapped_column(String(20), default="string")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class OperationLog(StateBase):
    __tablename__ = "operation_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    level: Mapped[str] = mapped_column(String(20), default="INFO")
    module: Mapped[str] = mapped_column(String(50))
    action: Mapped[str] = mapped_column(String(80))
    message: Mapped[str] = mapped_column(Text)
    principal: Mapped[str] = mapped_column(String(200), default="")
    actor_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Collection(StateBase):
    __tablename__ = "collections"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    cover: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    visible_on_home: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    goal: Mapped[str] = mapped_column(Text, default="", server_default="")
    audience: Mapped[str] = mapped_column(Text, default="", server_default="")
    prerequisites: Mapped[str] = mapped_column(Text, default="", server_default="")
    item_intro: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class CollectionItem(StateBase):
    __tablename__ = "collection_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    collection_id: Mapped[int] = mapped_column(ForeignKey("collections.id", ondelete="CASCADE"), index=True)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    item_type: Mapped[str] = mapped_column(String(20), default="resource", server_default="resource", index=True)
    catalog_entry_id: Mapped[str | None] = mapped_column(String(35), nullable=True, index=True)
    note: Mapped[str] = mapped_column(Text, default="", server_default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (
        UniqueConstraint("collection_id", "resource_id"),
        UniqueConstraint("collection_id", "catalog_entry_id"),
        CheckConstraint("item_type IN ('resource', 'catalog_entry')"),
    )


class Share(StateBase):
    __tablename__ = "shares"
    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    creator_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    object_type: Mapped[str] = mapped_column(String(20), index=True)
    object_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    access_mode: Mapped[str] = mapped_column(String(20), default="code", index=True)
    code_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    code_version: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    download_count: Mapped[int] = mapped_column(Integer, default=0)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ShareVerifyAttempt(StateBase):
    __tablename__ = "share_verify_attempts"
    id: Mapped[int] = mapped_column(primary_key=True)
    share_token: Mapped[str] = mapped_column(String(64), index=True)
    ip_hash: Mapped[str] = mapped_column(String(64), index=True)
    fail_count: Mapped[int] = mapped_column(Integer, default=0)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    challenge_required_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    __table_args__ = (UniqueConstraint("share_token", "ip_hash"),)


class User(StateBase):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(32))
    username_normalized: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_by_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    role: Mapped[str] = mapped_column(String(20), default="viewer", index=True)


class Submission(StateBase):
    __tablename__ = "submissions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    resource_name: Mapped[str] = mapped_column(String(120))
    resource_type: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(Text, default="")
    source_url: Mapped[str] = mapped_column(String(1000), default="")
    download_url: Mapped[str] = mapped_column(String(2000), default="")
    copyright_note: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    admin_note: Mapped[str] = mapped_column(Text, default="")
    reviewed_by: Mapped[str] = mapped_column(String(100), default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class UserSession(StateBase):
    __tablename__ = "user_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AdminSession(StateBase):
    __tablename__ = "admin_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    principal: Mapped[str] = mapped_column(String(200), index=True)
    authority: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    revocation_reason: Mapped[str] = mapped_column(String(40), default="")
    epoch: Mapped[int] = mapped_column(Integer, default=1, index=True)
    created_ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class UserFavorite(StateBase):
    __tablename__ = "user_favorites"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    resource_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (
        UniqueConstraint("user_id", "resource_id"),
        Index("ix_user_favorites_user_created_at", "user_id", "created_at"),
    )


class UserResourceHistory(StateBase):
    __tablename__ = "user_resource_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    resource_id: Mapped[str] = mapped_column(String(64), index=True)
    first_viewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_viewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    view_count: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    __table_args__ = (
        UniqueConstraint("user_id", "resource_id"),
        Index("ix_user_resource_history_user_last_viewed_at", "user_id", "last_viewed_at"),
    )


class UserPlaybackProgress(StateBase):
    __tablename__ = "user_playback_progress"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    resource_id: Mapped[str] = mapped_column(String(64), index=True)
    position_seconds: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    last_played_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    __table_args__ = (
        UniqueConstraint("user_id", "resource_id"),
        Index("ix_user_playback_progress_user_last_played_at", "user_id", "last_played_at"),
        Index("ix_user_playback_progress_user_completed", "user_id", "completed"),
    )


class SyncRun(IndexBase):
    __tablename__ = "sync_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    sync_type: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), index=True)
    folders_scanned: Mapped[int] = mapped_column(Integer, default=0)
    resources_scanned: Mapped[int] = mapped_column(Integer, default=0)
    added_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    removed_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str] = mapped_column(Text, default="")
    current_path: Mapped[str] = mapped_column(String(1500), default="")
    roots_total: Mapped[int] = mapped_column(Integer, default=0)
    roots_completed: Mapped[int] = mapped_column(Integer, default=0)
    roots_failed: Mapped[int] = mapped_column(Integer, default=0)
    list_requests: Mapped[int] = mapped_column(Integer, default=0)
    trigger_source: Mapped[str] = mapped_column(String(20), default="auto")
    target_paths_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    force_refresh_paths_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    renamed_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_verified_count: Mapped[int] = mapped_column(Integer, default=0)
    refresh_true_count: Mapped[int] = mapped_column(Integer, default=0)
    auto_interrupted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    auto_resumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SyncRootResult(IndexBase):
    __tablename__ = "sync_root_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    sync_run_id: Mapped[int] = mapped_column(ForeignKey("sync_runs.id", ondelete="CASCADE"), index=True)
    root_mapping_id: Mapped[int] = mapped_column(Integer, index=True)
    root_path: Mapped[str] = mapped_column(String(1500))
    status: Mapped[str] = mapped_column(String(30), index=True)
    folders_scanned: Mapped[int] = mapped_column(Integer, default=0)
    resources_scanned: Mapped[int] = mapped_column(Integer, default=0)
    added_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    removed_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str] = mapped_column(Text, default="")
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("sync_run_id", "root_mapping_id"),)


class SyncChange(IndexBase):
    __tablename__ = "sync_changes"
    id: Mapped[int] = mapped_column(primary_key=True)
    sync_run_id: Mapped[int] = mapped_column(ForeignKey("sync_runs.id", ondelete="CASCADE"), index=True)
    object_type: Mapped[str] = mapped_column(String(20))
    object_id: Mapped[str] = mapped_column(String(64))
    change_type: Mapped[str] = mapped_column(String(20))  # added/updated/removed/renamed
    old_path: Mapped[str | None] = mapped_column(String(1500), nullable=True)
    new_path: Mapped[str | None] = mapped_column(String(1500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("sync_run_id", "object_type", "object_id", "change_type"),)


class SyncCycle(IndexBase):
    __tablename__ = "sync_cycles"
    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_type: Mapped[str] = mapped_column(String(30), default="normal", index=True)
    status: Mapped[str] = mapped_column(String(30), default="planned", index=True)
    anchor_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    planned_folder_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_folder_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_folder_count: Mapped[int] = mapped_column(Integer, default=0)
    carry_over_count: Mapped[int] = mapped_column(Integer, default=0)
    windows_total: Mapped[int] = mapped_column(Integer, default=4)
    windows_completed: Mapped[int] = mapped_column(Integer, default=0)
    alist_list_requests: Mapped[int] = mapped_column(Integer, default=0)
    changed_scope_count: Mapped[int] = mapped_column(Integer, default=0)
    unchanged_scope_count: Mapped[int] = mapped_column(Integer, default=0)
    fts_rebuilt_count: Mapped[int] = mapped_column(Integer, default=0)
    renamed_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_verified_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SyncCycleItem(IndexBase):
    __tablename__ = "sync_cycle_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("sync_cycles.id", ondelete="CASCADE"), index=True)
    folder_id: Mapped[str] = mapped_column(String(64), index=True)
    folder_path: Mapped[str] = mapped_column(String(1500))
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0, index=True)
    window_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    __table_args__ = (UniqueConstraint("cycle_id", "folder_id"),)


class FolderScanState(IndexBase):
    __tablename__ = "folder_scan_state"
    folder_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    path: Mapped[str] = mapped_column(String(1500), index=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_verified_cycle_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(64), default="")
    fingerprint_version: Mapped[int] = mapped_column(Integer, default=1)
    last_scan_result: Mapped[str] = mapped_column(String(30), default="never")
    last_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class CatalogSearchProjectionState(IndexBase):
    """index.db 端的投影水位：记录每个 entry 已投影到的 catalog revision。

    与 catalog_search_fts 在同一 index 事务写入，保证 FTS 与水位原子推进。
    消费者据此跳过已应用或更旧的 outbox 行，实现崩溃重放幂等与旧不覆盖新。
    """
    __tablename__ = "catalog_search_projection_state"
    entry_id: Mapped[str] = mapped_column(String(35), primary_key=True)
    applied_revision: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)



class CatalogSuggestion(StateBase):
    """A2 整理建议：影子模式生成的候选草稿，与正式 catalog 内容分表。

    每行记录一条由 A1 resource_name_parser 推导出的整理建议，包含来源文件
    指纹、解析器版本、建议类型、拟关联的 entry/release/asset、受控建议字段、
    evidence 依据与置信度。状态在 pending → reviewed → applied/rejected 间
    流转；apply 产生的内容修订记录于 catalog_revisions，撤销产生新修订而非
    删除底层文件。相同 (source_file_id, file_fingerprint, parser_version,
    suggestion_kind) 幂等：重跑不重复生成草稿，且不覆盖人工已确认的结果。
    """
    __tablename__ = "catalog_suggestions"
    suggestion_id: Mapped[str] = mapped_column(String(35), primary_key=True)
    source_file_id: Mapped[str] = mapped_column(String(64), index=True)
    file_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    parser_version: Mapped[str] = mapped_column(String(20))
    suggestion_kind: Mapped[str] = mapped_column(String(30), index=True)
    target_entry_id: Mapped[str | None] = mapped_column(String(35), nullable=True, index=True)
    target_release_id: Mapped[str | None] = mapped_column(String(35), nullable=True, index=True)
    target_asset_id: Mapped[str | None] = mapped_column(String(35), nullable=True, index=True)
    suggested_fields_json: Mapped[str] = mapped_column(Text, default="{}")
    evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    reviewed_by: Mapped[str] = mapped_column(String(100), default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_revision_id: Mapped[str | None] = mapped_column(String(35), nullable=True)
    reject_reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    __table_args__ = (
        UniqueConstraint(
            "source_file_id",
            "file_fingerprint",
            "parser_version",
            "suggestion_kind",
            name="ux_catalog_suggestions_idempotent",
        ),
        Index(
            "ix_catalog_suggestions_kind_status",
            "suggestion_kind",
            "status",
        ),
        CheckConstraint(
            "suggestion_kind IN ('new_entry', 'new_release', 'asset', 'candidate_duplicate', 'conflict')",
            name="ck_catalog_suggestions_kind",
        ),
        CheckConstraint(
            "status IN ('pending', 'reviewed', 'applied', 'rejected')",
            name="ck_catalog_suggestions_status",
        ),
    )



class SitePresentation(StateBase):
    """B1 站点呈现配置：场景预设、主题变量、导航与首页区块顺序。

    单例（id=1），保存当前生效的轻量版本化配置。preset 为预设标识
    （software/tutorial/custom）；theme_tokens/navigation/home_blocks 以受控
    JSON 文本存储，经 pydantic schema 验证后写入，不直接执行用户代码。
    config_revision 单调递增，每次发布写一条 SitePresentationRevision 历史快照
    用于回退。enabled=False 时首页回退到默认区块顺序，旧默认主题仍可恢复。
    """

    __tablename__ = "site_presentation"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    preset: Mapped[str] = mapped_column(String(20), default="custom")
    theme_tokens_json: Mapped[str] = mapped_column(Text, default="{}")
    navigation_json: Mapped[str] = mapped_column(Text, default="[]")
    home_blocks_json: Mapped[str] = mapped_column(Text, default="[]")
    config_revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    updated_by: Mapped[str] = mapped_column(String(100), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    __table_args__ = (
        CheckConstraint(
            "preset IN ('software', 'tutorial', 'custom')",
            name="ck_site_presentation_preset",
        ),
    )


class SitePresentationRevision(StateBase):
    """B1 站点呈现配置历史快照：每次发布保留上一配置，支持回退。

    回退生成新 revision 并走同一发布流程，不覆盖历史；保留足够信息恢复
    theme_tokens/navigation/home_blocks。撤销/回退不破坏既有身份。
    """

    __tablename__ = "site_presentation_revisions"
    revision_id: Mapped[int] = mapped_column(primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, index=True)
    preset: Mapped[str] = mapped_column(String(20), default="custom")
    theme_tokens_json: Mapped[str] = mapped_column(Text, default="{}")
    navigation_json: Mapped[str] = mapped_column(Text, default="[]")
    home_blocks_json: Mapped[str] = mapped_column(Text, default="[]")
    summary: Mapped[str] = mapped_column(String(200), default="")
    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class SetupWizardState(StateBase):
    """B2 首次建站向导状态：单例（id=1）记录七步进度。

    current_step 为当前步骤标识（connect/scope/preset/samples/brand/preview/publish），
    completed_steps_json 为已完成步骤 JSON 数组，每步对应 *_done 布尔标记。
    wizard_completed=1 表示向导已完成（正常走完或跳过）。向导在 setup_completed
    标记前置位运行；publish/skip 步骤才写入 setup_completed。
    """

    __tablename__ = "setup_wizard_state"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    current_step: Mapped[str] = mapped_column(String(20), default="connect")
    completed_steps_json: Mapped[str] = mapped_column(Text, default="[]")
    connect_done: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    scope_done: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    preset_done: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    samples_done: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    brand_done: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    preview_done: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    publish_done: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    wizard_completed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    started_at: Mapped[str] = mapped_column(String(40), default="")
    completed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)

class HealthCheckState(StateBase):
    """M6 健康检查组件状态：每组件一行（component 唯一）。

    component 为 database/alist/storage，status 为 healthy/degraded/unhealthy。
    /api/ready 就绪探针检查后更新对应行；last_error 记录最近一次错误信息。
    """

    __tablename__ = "health_check_state"
    id: Mapped[int] = mapped_column(primary_key=True)
    component: Mapped[str] = mapped_column(String(40), unique=True)
    status: Mapped[str] = mapped_column(String(20))
    last_check_at: Mapped[str] = mapped_column(String(40))
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

class QualityTodo(StateBase):
    """A4 内容质量待办项：将缺说明、失效位置、旧版待复核、疑似重复、
    无结果查询等变为可处理队列。

    每行记录一条检测到的质量问题或用户反馈。todo_type 标识问题类别，
    target_type/target_id 指向受影响实体。status 在 open → dismissed/resolved/wontfix
    间流转。source 区分自动检测与用户反馈。相同 (todo_type, target_type, target_id)
    的 open 项幂等：重复检测不堆积，只更新 detail_json 与 updated_at。
    detail_json 存储四种状态检查结果（file_exists/download_ready/preview_ready/
    content_reviewed）及其他结构化详情。隐藏资源不出现在无权限的队列中。
    """

    __tablename__ = "quality_todos"
    todo_id: Mapped[str] = mapped_column(String(35), primary_key=True)
    todo_type: Mapped[str] = mapped_column(String(30), index=True)
    target_type: Mapped[str] = mapped_column(String(20))
    target_id: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(10), default="medium")
    title: Mapped[str] = mapped_column(String(200))
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    source: Mapped[str] = mapped_column(String(20), default="auto_detection")
    detection_run_id: Mapped[str | None] = mapped_column(String(35), nullable=True, index=True)
    dismissed_by: Mapped[str] = mapped_column(String(100), default="")
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismiss_reason: Mapped[str] = mapped_column(Text, default="")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    __table_args__ = (
        Index(
            "ux_quality_todos_open_dedup",
            "todo_type",
            "target_type",
            "target_id",
            unique=True,
            sqlite_where=text("status = 'open'"),
        ),
        Index(
            "ix_quality_todos_type_status",
            "todo_type",
            "status",
        ),
        CheckConstraint(
            "todo_type IN ('missing_description', 'stale_location', 'old_version_review', "
            "'source_conflict', 'suspected_duplicate', 'no_result_query')",
            name="ck_quality_todos_type",
        ),
        CheckConstraint(
            "status IN ('open', 'dismissed', 'resolved', 'wontfix')",
            name="ck_quality_todos_status",
        ),
        CheckConstraint(
            "severity IN ('low', 'medium', 'high')",
            name="ck_quality_todos_severity",
        ),
        CheckConstraint(
            "source IN ('auto_detection', 'user_feedback')",
            name="ck_quality_todos_source",
        ),
    )


class QualityDetectionRun(StateBase):
    """A4 检测运行记录：跟踪每次批量检测的预算消耗与发现数量。

    用于控制检测预算（budget_ms/actual_ms）和幂等性。status 为 running/completed/timeout。
    items_found 为新发现的待办项数，items_deduplicated 为因幂等约束跳过的重复数。
    """

    __tablename__ = "quality_detection_runs"
    run_id: Mapped[str] = mapped_column(String(35), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    items_found: Mapped[int] = mapped_column(Integer, default=0)
    items_deduplicated: Mapped[int] = mapped_column(Integer, default=0)
    budget_ms: Mapped[int] = mapped_column(Integer, default=5000)
    actual_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="running")
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'timeout')",
            name="ck_quality_detection_runs_status",
        ),
    )


class SearchQueryLog(StateBase):
    """A4 搜索查询日志：记录查询词与结果数，用于无结果查询聚合。

    每次资源搜索写入一行，不设唯一约束（允许重复查询堆积）。
    检测时按 query 聚合 result_count=0 的行，生成 no_result_query 待办。
    user_id 为发起搜索的用户，nullable 允许匿名搜索日志。
    """

    __tablename__ = "search_query_logs"
    log_id: Mapped[int] = mapped_column(primary_key=True)
    query: Mapped[str] = mapped_column(String(200), index=True)
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    user_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    content_type_filter: Mapped[str | None] = mapped_column(String(40), nullable=True)
    platform_filter: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ContentFeedback(StateBase):
    """A4 用户内容反馈：用户报告资源条目/交付物/位置的问题。

    feedback_kind 标识问题类别（broken_link/wrong_info/missing_content/other）。
    status 在 pending → reviewed/resolved 间流转。提交反馈时自动创建一条
    source='user_feedback' 的 QualityTodo，管理员处理反馈后同步更新关联待办。
    description 限 1000 字符，admin_note 记录管理员处理备注。
    """

    __tablename__ = "content_feedback"
    feedback_id: Mapped[str] = mapped_column(String(35), primary_key=True)
    user_id: Mapped[int] = mapped_column(index=True)
    target_type: Mapped[str] = mapped_column(String(20))
    target_id: Mapped[str] = mapped_column(String(64), index=True)
    feedback_kind: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    admin_note: Mapped[str] = mapped_column(Text, default="")
    reviewed_by: Mapped[str] = mapped_column(String(100), default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    todo_id: Mapped[str | None] = mapped_column(String(35), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    __table_args__ = (
        CheckConstraint(
            "target_type IN ('entry', 'asset', 'location')",
            name="ck_content_feedback_target_type",
        ),
        CheckConstraint(
            "feedback_kind IN ('broken_link', 'wrong_info', 'missing_content', 'other')",
            name="ck_content_feedback_kind",
        ),
        CheckConstraint(
            "status IN ('pending', 'reviewed', 'resolved')",
            name="ck_content_feedback_status",
        ),
    )

class AIProviderConfig(StateBase):
    """A3 AI 提供方配置：管理员配置本地或远程 AI 服务。

    provider_type 标识提供方类型（local_ollama/openai_compatible/custom）。
    api_key_encrypted 存储加密后的 API key（远程服务用）。enabled 默认 False，
    管理员显式启用后才能用于生成。daily_budget_tokens/requests 控制每日用量，
    timeout_seconds/max_retries 控制单次请求行为。关闭 AI 后核心功能不受影响。
    """

    __tablename__ = "ai_provider_configs"
    config_id: Mapped[str] = mapped_column(String(35), primary_key=True)
    provider_type: Mapped[str] = mapped_column(String(30))
    display_name: Mapped[str] = mapped_column(String(100))
    endpoint_url: Mapped[str] = mapped_column(String(500), default="")
    api_key_encrypted: Mapped[str] = mapped_column(Text, default="")
    model_name: Mapped[str] = mapped_column(String(100), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    daily_budget_tokens: Mapped[int] = mapped_column(Integer, default=100000)
    daily_budget_requests: Mapped[int] = mapped_column(Integer, default=100)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30)
    max_retries: Mapped[int] = mapped_column(Integer, default=2)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    __table_args__ = (
        CheckConstraint(
            "provider_type IN ('local_ollama', 'openai_compatible', 'custom')",
            name="ck_ai_provider_config_type",
        ),
    )


class AIGenerationDraft(StateBase):
    """A3 AI 生成草稿：AI 为资源条目生成的简介/标签/别名/用途草稿。

    与 CatalogSuggestion 分表：A2 来源于规则解析，A3 来源于 AI 生成。
    输出保留 provider_type/model_name/prompt_template_version/source_pointers_json
    用于追溯。candidate_status 在 pending → accepted/rejected/modified 间流转。
    accepted 草稿写入正式 catalog 内容并记录修订。input_material_hash 用于幂等：
    相同输入不重复生成 pending 草稿。不将猜测的许可证/作者/版本直接写为已验证事实。
    """

    __tablename__ = "ai_generation_drafts"
    draft_id: Mapped[str] = mapped_column(String(35), primary_key=True)
    target_type: Mapped[str] = mapped_column(String(20))
    target_id: Mapped[str] = mapped_column(String(64), index=True)
    field_type: Mapped[str] = mapped_column(String(20), index=True)
    provider_type: Mapped[str] = mapped_column(String(30))
    model_name: Mapped[str] = mapped_column(String(100), default="")
    prompt_template_version: Mapped[str] = mapped_column(String(20), default="1.0.0")
    source_pointers_json: Mapped[str] = mapped_column(Text, default="[]")
    generated_content: Mapped[str] = mapped_column(Text, default="")
    candidate_status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    input_material_hash: Mapped[str] = mapped_column(String(64), index=True)
    config_id: Mapped[str | None] = mapped_column(String(35), nullable=True, index=True)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    elapsed_ms: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str] = mapped_column(Text, default="")
    reviewed_by: Mapped[str] = mapped_column(String(100), default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    __table_args__ = (
        Index(
            "ux_ai_drafts_pending_dedup",
            "target_type",
            "target_id",
            "field_type",
            "input_material_hash",
            unique=True,
            sqlite_where=text("candidate_status = 'pending'"),
        ),
        Index(
            "ix_ai_drafts_target_field",
            "target_id",
            "field_type",
        ),
        CheckConstraint(
            "target_type = 'entry'",
            name="ck_ai_draft_target_type",
        ),
        CheckConstraint(
            "field_type IN ('summary', 'tags', 'aliases', 'usage_note')",
            name="ck_ai_draft_field_type",
        ),
        CheckConstraint(
            "candidate_status IN ('pending', 'accepted', 'rejected', 'modified')",
            name="ck_ai_draft_status",
        ),
    )


class AIBudgetUsage(StateBase):
    """A3 AI 预算用量：按 config_id + date 记录每日 token 和请求消耗。

    每行记录一个 provider config 在某一天的累计用量。生成前检查是否超预算，
    生成后更新用量。date 为 YYYY-MM-DD 字符串。
    """

    __tablename__ = "ai_budget_usage"
    usage_id: Mapped[int] = mapped_column(primary_key=True)
    config_id: Mapped[str] = mapped_column(String(35), index=True)
    date: Mapped[str] = mapped_column(String(10), index=True)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    requests_used: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    __table_args__ = (
        UniqueConstraint("config_id", "date", name="ux_ai_budget_usage_config_date"),
    )

class MetricEvent(StateBase):
    """G2 指标事件：统一事件追踪表。

    记录 download_redirect_issued、search_performed、resource_selected、
    site_setup_completed 等事件。event_data 为 JSON 文本，可能含查询
    等敏感信息，默认不集中上传。retention 由 metrics_retention_days 控制。
    """

    __tablename__ = "metric_events"
    id: Mapped[str] = mapped_column(String(35), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    event_data: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class MetricBaseline(StateBase):
    """G2 指标基线：为对比而快照的某时段聚合指标。

    G2a 上线前采集基线，G2b 上线后用相同口径比较。
    summary_json 为 JSON 文本，包含所有 metric_type → value 的映射。
    """

    __tablename__ = "metric_baselines"
    id: Mapped[str] = mapped_column(String(35), primary_key=True)
    label: Mapped[str] = mapped_column(String(128))
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    summary_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MetricSummary(StateBase):
    """G2 指标聚合：某时段某 metric_type 的聚合值。

    metric_type 包括 resource_selection_success_rate、organize_time_per_100、
    search_hit_rate、no_result_handling、first_site_setup_time、
    update_revisit_rate、support_cost 等。
    """

    __tablename__ = "metric_summaries"
    id: Mapped[str] = mapped_column(String(35), primary_key=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    metric_type: Mapped[str] = mapped_column(String(64), index=True)
    value: Mapped[float] = mapped_column(Float, default=0.0)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class DeliveryPackage(StateBase):
    """T2 交付包：版本明确的客户交付清单快照。

    保存名称、项目说明、修订、选定的 asset_id/file_id 清单、有效期和发布记录。
    首版只做交付清单快照，新增版本不改变已发布交付包。
    """

    __tablename__ = "delivery_packages"
    package_id: Mapped[str] = mapped_column(String(35), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    project_note: Mapped[str] = mapped_column(Text, default="")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    creator_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    access_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    code_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class DeliveryPackageItem(StateBase):
    """T2 交付包清单项：每项记录绑定时可靠内容指纹或上游对象版本。

    下载前检测到变化时禁止静默按旧版本交付，提示复核。
    """

    __tablename__ = "delivery_package_items"
    item_id: Mapped[int] = mapped_column(primary_key=True)
    package_id: Mapped[str] = mapped_column(ForeignKey("delivery_packages.package_id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[str | None] = mapped_column(String(35), nullable=True, index=True)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200), default="")
    bound_checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    bound_checksum_algorithm: Mapped[str | None] = mapped_column(String(20), nullable=True)
    bound_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (
        UniqueConstraint("package_id", "asset_id", name="ux_delivery_items_package_asset"),
        UniqueConstraint("package_id", "resource_id", name="ux_delivery_items_package_resource"),
    )

class APIToken(StateBase):
    """X2 API 访问令牌：限定动作和对象范围，可撤销。

    token_hash 存储 SHA-256 哈希，不存明文。scopes 为 JSON 数组，
    如 ["entry:read", "entry:write", "release:publish"]。
    """

    __tablename__ = "api_tokens"
    token_id: Mapped[str] = mapped_column(String(35), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(128), default="")
    scopes: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    created_by: Mapped[str] = mapped_column(String(200), default="")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class WebhookEndpoint(StateBase):
    """X2 Webhook 端点：签名、重试、事件 ID、去重和失败队列。

    event_types 为 JSON 数组，如 ["entry.created", "release.published"]。
    secret 用于 HMAC-SHA256 签名验证。
    """

    __tablename__ = "webhook_endpoints"
    endpoint_id: Mapped[str] = mapped_column(String(35), primary_key=True)
    url: Mapped[str] = mapped_column(String(500))
    secret: Mapped[str] = mapped_column(String(128), default="")
    event_types: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class WebhookDelivery(StateBase):
    """X2 Webhook 投递记录：事件 ID 去重、重试、失败队列。

    status: pending/delivered/failed
    event_id 用于幂等去重：同一 event_id 不重复投递。
    """

    __tablename__ = "webhook_deliveries"
    delivery_id: Mapped[str] = mapped_column(String(35), primary_key=True)
    endpoint_id: Mapped[str] = mapped_column(ForeignKey("webhook_endpoints.endpoint_id", ondelete="CASCADE"), index=True)
    event_id: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

class ProviderCompatRecord(StateBase):
    """X1 Provider 兼容测试记录：每个平台/版本的适配器兼容性结果。

    验收：所有支持平台有实际兼容记录。
    """

    __tablename__ = "provider_compat_records"
    id: Mapped[str] = mapped_column(String(35), primary_key=True)
    provider_type: Mapped[str] = mapped_column(String(40), index=True)
    adapter_version: Mapped[str] = mapped_column(String(100))
    platform: Mapped[str] = mapped_column(String(100), index=True)
    platform_version: Mapped[str] = mapped_column(String(100), default="")
    test_result: Mapped[str] = mapped_column(String(20), default="pass", index=True)
    tested_capabilities_json: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CloudDownloadTask(StateBase):
    """CloudSite 115 cloud download submission state.

    Persisted schema is intentionally minimal: only the owning user, an
    optional driver hash, lifecycle status, and a short display name are
    stored. Submitted URLs and credentials are never persisted in this
    table. driver_hash is not unique because multiple users may submit
    the same driver hash.
    """

    __tablename__ = "cloud_download_tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    driver_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    display_name: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
