from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
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


class Notification(StateBase):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    level: Mapped[str] = mapped_column(String(20), default="info", index=True)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    source: Mapped[str] = mapped_column(String(30), default="manual")
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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


class FolderIdentity(StateBase):
    __tablename__ = "folder_identities"
    folder_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    current_path: Mapped[str] = mapped_column(String(1500), index=True)
    root_mapping_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_name: Mapped[str] = mapped_column(String(500), default="")
    identity_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    fingerprint_version: Mapped[int] = mapped_column(Integer, default=1)
    created_from: Mapped[str] = mapped_column(String(30), default="new_folder")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class FolderIdentityHistory(StateBase):
    __tablename__ = "folder_identity_histories"
    id: Mapped[int] = mapped_column(primary_key=True)
    folder_id: Mapped[str] = mapped_column(
        ForeignKey("folder_identities.folder_id", ondelete="RESTRICT"), index=True
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


class CatalogEntry(StateBase):
    __tablename__ = "catalog_entries"
    entry_id: Mapped[str] = mapped_column(String(35), primary_key=True)
    content_type: Mapped[str] = mapped_column(String(40), index=True)
    slug: Mapped[str] = mapped_column(String(160), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    cover_resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CatalogRelease(StateBase):
    __tablename__ = "catalog_releases"
    release_id: Mapped[str] = mapped_column(String(35), primary_key=True)
    entry_id: Mapped[str] = mapped_column(
        ForeignKey("catalog_entries.entry_id", ondelete="CASCADE"), index=True
    )
    slug: Mapped[str] = mapped_column(String(160), default="unversioned")
    title: Mapped[str] = mapped_column(String(200))
    release_notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    channel: Mapped[str] = mapped_column(String(20), default="unknown", server_default="unknown", index=True)
    release_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_recommended: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        UniqueConstraint("entry_id", "slug"),
        Index(
            "ux_catalog_releases_one_recommended_per_entry",
            "entry_id",
            unique=True,
            sqlite_where=text("is_recommended = 1"),
        ),
    )


class CatalogAsset(StateBase):
    __tablename__ = "catalog_assets"
    asset_id: Mapped[str] = mapped_column(String(35), primary_key=True)
    release_id: Mapped[str] = mapped_column(
        ForeignKey("catalog_releases.release_id", ondelete="CASCADE"), index=True
    )
    slug: Mapped[str] = mapped_column(String(160))
    display_name: Mapped[str] = mapped_column(String(500))
    platform: Mapped[str] = mapped_column(String(40), default="")
    kind: Mapped[str] = mapped_column(String(40), default="file")
    architecture: Mapped[str] = mapped_column(String(20), default="unknown", server_default="unknown", index=True)
    package_type: Mapped[str] = mapped_column(String(40), default="unknown", server_default="unknown")
    language: Mapped[str] = mapped_column(String(20), default="unknown", server_default="unknown", index=True)
    build_label: Mapped[str] = mapped_column(String(120), default="", server_default="")
    checksum: Mapped[str | None] = mapped_column(String(200), nullable=True)
    checksum_algorithm: Mapped[str | None] = mapped_column(String(20), nullable=True)
    size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    __table_args__ = (UniqueConstraint("release_id", "slug"),)


class CatalogLocation(StateBase):
    __tablename__ = "catalog_locations"
    location_id: Mapped[str] = mapped_column(String(35), primary_key=True)
    asset_id: Mapped[str] = mapped_column(
        ForeignKey("catalog_assets.asset_id", ondelete="CASCADE"), index=True
    )
    resource_id: Mapped[str] = mapped_column(String(64), index=True)
    root_mapping_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    label: Mapped[str] = mapped_column(String(100), default="")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    __table_args__ = (UniqueConstraint("asset_id", "resource_id"),)



class CatalogTag(StateBase):
    __tablename__ = "catalog_tags"
    tag_id: Mapped[str] = mapped_column(String(35), primary_key=True)
    slug: Mapped[str] = mapped_column(String(60), unique=True)
    display_name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    __table_args__ = (CheckConstraint("slug = lower(slug)", name="ck_catalog_tags_slug_normalized"),)


class CatalogTagAssignment(StateBase):
    __tablename__ = "catalog_tag_assignments"
    tag_id: Mapped[str] = mapped_column(
        ForeignKey("catalog_tags.tag_id", ondelete="CASCADE"), primary_key=True
    )
    target_type: Mapped[str] = mapped_column(String(20), primary_key=True)
    target_id: Mapped[str] = mapped_column(String(35), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (
        Index("ix_catalog_tag_assignments_target", "target_type", "target_id"),
        CheckConstraint(
            "target_type IN ('entry', 'release', 'asset')",
            name="ck_catalog_tag_assignments_target_type",
        ),
    )


class CatalogRelation(StateBase):
    __tablename__ = "catalog_relations"
    relation_id: Mapped[str] = mapped_column(String(35), primary_key=True)
    from_entry_id: Mapped[str] = mapped_column(
        ForeignKey("catalog_entries.entry_id", ondelete="CASCADE"), index=True
    )
    to_entry_id: Mapped[str] = mapped_column(
        ForeignKey("catalog_entries.entry_id", ondelete="CASCADE"), index=True
    )
    relation_type: Mapped[str] = mapped_column(String(40), index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (
        UniqueConstraint("from_entry_id", "to_entry_id", "relation_type"),
        CheckConstraint("from_entry_id != to_entry_id", name="ck_catalog_relations_no_self"),
    )


class CatalogRevision(StateBase):
    __tablename__ = "catalog_revisions"
    revision_id: Mapped[str] = mapped_column(String(35), primary_key=True)
    target_type: Mapped[str] = mapped_column(String(20))
    target_id: Mapped[str] = mapped_column(String(35))
    action: Mapped[str] = mapped_column(String(40))
    actor: Mapped[str] = mapped_column(String(100))
    source: Mapped[str] = mapped_column(String(40), default="admin")
    base_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resulting_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    before_json: Mapped[str] = mapped_column(Text, default="{}")
    after_json: Mapped[str] = mapped_column(Text, default="{}")
    diff_json: Mapped[str] = mapped_column(Text, default="{}")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (
        Index("ix_catalog_revisions_target", "target_type", "target_id"),
        Index("ix_catalog_revisions_action", "action"),
        Index("ix_catalog_revisions_actor", "actor"),
        Index("ix_catalog_revisions_created_at", "created_at"),
        CheckConstraint(
            "target_type IN ('entry', 'release', 'asset', 'location', 'tag', 'relation')",
            name="ck_catalog_revisions_target_type",
        ),
        CheckConstraint(
            "action IN ('create', 'update', 'delete', 'publish', 'unpublish', 'archive', 'disable')",
            name="ck_catalog_revisions_action",
        ),
    )
