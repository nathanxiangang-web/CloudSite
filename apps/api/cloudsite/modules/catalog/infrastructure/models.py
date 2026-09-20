"""Catalog-owned SQLAlchemy state models.

Declarations remain schema-compatible with the legacy cloudsite.models symbols.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ....platform.db import StateBase


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
    publicly_visible: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", index=True)
    featured: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", index=True)


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


class CatalogSearchOutbox(StateBase):
    """ProjectionOutbox 行：catalog 写操作同事务入队，消费者异步投影到 index.db。

    消费者按 created_at 升序处理未消费行（consumed_at IS NULL）。对每行：
    - 若 entry 当前 revision > outbox.revision：说明已有更新的 outbox 行排队，
      跳过本行（旧 revision 不覆盖新数据），仅标记 consumed。
    - 否则按 action 投影：upsert 写 catalog_search_fts，delete 移除。
    消费在同一 index 事务中更新 catalog_search_projection_state.applied_revision，
    确认后回写 state.db outbox.consumed_at。崩溃重放幂等：applied_revision >=
    outbox.revision 的行直接跳过。
    """
    __tablename__ = "catalog_search_outbox"
    outbox_id: Mapped[str] = mapped_column(String(35), primary_key=True)
    entry_id: Mapped[str] = mapped_column(String(35), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(20), default="upsert")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        Index("ix_catalog_search_outbox_pending", "created_at", "outbox_id"),
        CheckConstraint(
            "action IN ('upsert', 'delete')",
            name="ck_catalog_search_outbox_action",
        ),
    )


class CatalogFavorite(StateBase):
    """C4 资源关注：用户关注一个 catalog 条目（整个软件/图库/视频条目）。

    与 UserFavorite（文件级收藏）严格分离：本表指向 catalog_entries.entry_id，
    不指向单个 resource_id。语义为"关注这个条目的更新动态"，出现在账号页
    "我的关注"列表，并作为更新通知的受众来源。文件收藏/历史/播放进度语义
    零改动，仍指向原文件，不自动提升为关注整个软件。
    """

    __tablename__ = "catalog_favorites"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    entry_id: Mapped[str] = mapped_column(
        ForeignKey("catalog_entries.entry_id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (
        UniqueConstraint("user_id", "entry_id"),
        Index("ix_catalog_favorites_user_created_at", "user_id", "created_at"),
    )


class CatalogSubscription(StateBase):
    """C4 更新通知订阅：记录用户对某条目更新通知的开关状态。

    关注条目时同步创建本行且 notify_enabled=True；用户可独立退订
    （notify_enabled=False）而保留关注。发布新 release 时仅向
    notify_enabled=True 的订阅者推送通知。
    """

    __tablename__ = "catalog_subscriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    entry_id: Mapped[str] = mapped_column(
        ForeignKey("catalog_entries.entry_id", ondelete="CASCADE"), index=True
    )
    notify_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    __table_args__ = (
        UniqueConstraint("user_id", "entry_id"),
        Index("ix_catalog_subscriptions_entry_enabled", "entry_id", "notify_enabled"),
    )


class CatalogReleaseNotification(StateBase):
    """C4 更新通知去重幂等记录：按 (release_id, user_id) 唯一。

    发布 release 时对每位订阅者尝试插入本行；若已存在则跳过通知，
    确保 release 重复发布（先 publish 再 unpublish 再 publish）不重复
    通知同一用户。取关后保留本行，避免重新关注后对同一 release 重复通知。
    """

    __tablename__ = "catalog_release_notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    release_id: Mapped[str] = mapped_column(
        ForeignKey("catalog_releases.release_id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    notification_id: Mapped[int | None] = mapped_column(
        ForeignKey("notifications.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("release_id", "user_id"),)


__all__ = [
    "CatalogEntry",
    "CatalogRelease",
    "CatalogAsset",
    "CatalogLocation",
    "CatalogTag",
    "CatalogTagAssignment",
    "CatalogRelation",
    "CatalogRevision",
    "CatalogSearchOutbox",
    "CatalogFavorite",
    "CatalogSubscription",
    "CatalogReleaseNotification",
]
