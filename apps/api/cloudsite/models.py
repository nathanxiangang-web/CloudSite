from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import IndexBase, StateBase


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AListConnection(StateBase):
    __tablename__ = "alist_connections"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    base_url: Mapped[str] = mapped_column(String(500), default="")
    base_path: Mapped[str] = mapped_column(String(1000), default="/")
    username: Mapped[str] = mapped_column(String(200), default="")
    password_ciphertext: Mapped[str] = mapped_column(Text, default="")
    remember_credentials: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    last_test_status: Mapped[str] = mapped_column(String(40), default="untested")
    last_test_message: Mapped[str] = mapped_column(Text, default="")
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_type: Mapped[str] = mapped_column(String(40), default="generic_alist")
    provider_capability_version: Mapped[int] = mapped_column(Integer, default=1)
    provider_capabilities_json: Mapped[str] = mapped_column(Text, default="")
    capabilities_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SiteSettings(StateBase):
    __tablename__ = "site_settings"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    site_name: Mapped[str] = mapped_column(String(100), default="CloudSite")
    home_title: Mapped[str] = mapped_column(String(200), default="把网盘变成好看的资源网站")
    description: Mapped[str] = mapped_column(String(500), default="软件、图片、视频、文档、文件，集中管理，轻松搜索，便捷分享")
    share_image_name: Mapped[str] = mapped_column(String(255), default="")
    recent_limit: Mapped[int] = mapped_column(Integer, default=6)
    popular_limit: Mapped[int] = mapped_column(Integer, default=6)
    collection_limit: Mapped[int] = mapped_column(Integer, default=4)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SystemSetting(StateBase):
    __tablename__ = "system_settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    value_type: Mapped[str] = mapped_column(String(20), default="string")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ContentRootMapping(StateBase):
    __tablename__ = "content_root_mappings"
    id: Mapped[int] = mapped_column(primary_key=True)
    content_type: Mapped[str] = mapped_column(String(40), index=True)
    display_name: Mapped[str] = mapped_column(String(100))
    alist_path: Mapped[str] = mapped_column(String(1000), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class DownloadEvent(StateBase):
    __tablename__ = "download_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[str] = mapped_column(String(64), index=True)
    result: Mapped[str] = mapped_column(String(20))
    error_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(20), default="public")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DownloadDiagnostic(StateBase):
    __tablename__ = "download_diagnostics"
    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    failed_step: Mapped[str] = mapped_column(String(40), default="")
    error_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    message: Mapped[str] = mapped_column(String(500), default="")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    target_host: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OperationLog(StateBase):
    __tablename__ = "operation_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    level: Mapped[str] = mapped_column(String(20), default="INFO")
    module: Mapped[str] = mapped_column(String(50))
    action: Mapped[str] = mapped_column(String(80))
    message: Mapped[str] = mapped_column(Text)
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class CollectionItem(StateBase):
    __tablename__ = "collection_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    collection_id: Mapped[int] = mapped_column(ForeignKey("collections.id", ondelete="CASCADE"), index=True)
    resource_id: Mapped[str] = mapped_column(String(64), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("collection_id", "resource_id"),)


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


class DownloadRateLimit(StateBase):
    __tablename__ = "download_rate_limits"
    id: Mapped[int] = mapped_column(primary_key=True)
    ip_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    recent_hits_json: Mapped[str] = mapped_column(Text, default="[]")
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, index=True)


class ResourceIdentity(StateBase):
    __tablename__ = "resource_identities"
    resource_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    current_path: Mapped[str | None] = mapped_column(String(1500), nullable=True, index=True)
    root_mapping_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_name: Mapped[str] = mapped_column(String(500), default="")
    last_extension: Mapped[str] = mapped_column(String(40), default="")
    last_mime_type: Mapped[str] = mapped_column(String(200), default="")
    last_size: Mapped[int] = mapped_column(BigInteger, default=0)
    last_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_object_id: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)
    content_hash: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    identity_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    fingerprint_version: Mapped[int] = mapped_column(Integer, default=1)
    created_from: Mapped[str] = mapped_column(String(30), default="new_resource")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ResourceIdentityHistory(StateBase):
    __tablename__ = "resource_identity_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[str] = mapped_column(
        ForeignKey("resource_identities.resource_id", ondelete="RESTRICT"), index=True
    )
    path: Mapped[str] = mapped_column(String(1500), index=True)
    event_type: Mapped[str] = mapped_column(String(30), index=True)
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    from_path: Mapped[str | None] = mapped_column(String(1500), nullable=True)
    to_path: Mapped[str | None] = mapped_column(String(1500), nullable=True)
    cycle_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Folder(IndexBase):
    __tablename__ = "folders"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(500), index=True)
    path: Mapped[str] = mapped_column(String(1500), unique=True)
    parent_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    content_type: Mapped[str] = mapped_column(String(40), index=True)
    root_mapping_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    depth: Mapped[int] = mapped_column(Integer, default=0)
    child_folder_count: Mapped[int] = mapped_column(Integer, default=0)
    resource_count: Mapped[int] = mapped_column(Integer, default=0)
    modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    missing_streak: Mapped[int] = mapped_column(Integer, default=0)
    missing_candidate_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    missing_last_observed_cycle_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Resource(IndexBase):
    __tablename__ = "resources"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(500), index=True)
    path: Mapped[str] = mapped_column(String(1500), unique=True)
    parent_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    content_type: Mapped[str] = mapped_column(String(40), index=True)
    root_mapping_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    extension: Mapped[str] = mapped_column(String(40), default="")
    mime_type: Mapped[str] = mapped_column(String(200), default="")
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    thumbnail: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    missing_streak: Mapped[int] = mapped_column(Integer, default=0)
    missing_candidate_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    missing_last_observed_cycle_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ResourceIdentityCandidate(IndexBase):
    __tablename__ = "resource_identity_candidates"
    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    observed_path: Mapped[str] = mapped_column(String(1500), index=True)
    observed_name: Mapped[str] = mapped_column(String(500), default="")
    observed_parent_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    root_mapping_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    content_type: Mapped[str] = mapped_column(String(40), default="file")
    matched_resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    candidate_resource_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    match_type: Mapped[str] = mapped_column(String(40), default="fingerprint")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    extension: Mapped[str] = mapped_column(String(40), default="")
    mime_type: Mapped[str] = mapped_column(String(200), default="")
    thumbnail: Mapped[str] = mapped_column(Text, default="")
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint("cycle_id", "observed_path"),)


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
    change_type: Mapped[str] = mapped_column(String(20))
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


class ProviderSyncState(IndexBase):
    __tablename__ = "provider_sync_state"
    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(Integer, index=True)
    root_mapping_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    strategy: Mapped[str] = mapped_column(String(30), default="rolling")
    cursor: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cursor_version: Mapped[int] = mapped_column(Integer, default=0)
    provider_generation: Mapped[str] = mapped_column(String(100), default="")
    last_delta_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_full_verify_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="idle")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    __table_args__ = (UniqueConstraint("connection_id", "root_mapping_id"),)
