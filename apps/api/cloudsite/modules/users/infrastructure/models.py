"""Users-owned SQLAlchemy models."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ....platform.db import StateBase


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(StateBase):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(32))
    username_normalized: Mapped[str] = mapped_column(
        String(32), unique=True, index=True
    )
    password_hash: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    password_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    disabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_by_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    role: Mapped[str] = mapped_column(
        String(20), default="viewer", index=True
    )


class UserSession(StateBase):
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_token_hash: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    created_ip_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    user_agent_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )


class UserFavorite(StateBase):
    __tablename__ = "user_favorites"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    resource_id: Mapped[str] = mapped_column(
        String(64),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
    )
    __table_args__ = (
        UniqueConstraint("user_id", "resource_id"),
        Index(
            "ix_user_favorites_user_created_at",
            "user_id",
            "created_at",
        ),
    )


class UserResourceHistory(StateBase):
    __tablename__ = "user_resource_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    resource_id: Mapped[str] = mapped_column(
        String(64),
        index=True,
    )
    first_viewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
    )
    last_viewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        index=True,
    )
    view_count: Mapped[int] = mapped_column(
        Integer,
        default=1,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )
    __table_args__ = (
        UniqueConstraint("user_id", "resource_id"),
        Index(
            "ix_user_resource_history_user_last_viewed_at",
            "user_id",
            "last_viewed_at",
        ),
    )


class UserPlaybackProgress(StateBase):
    __tablename__ = "user_playback_progress"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    resource_id: Mapped[str] = mapped_column(
        String(64),
        index=True,
    )
    position_seconds: Mapped[int] = mapped_column(
        Integer,
        default=0,
    )
    duration_seconds: Mapped[int] = mapped_column(
        Integer,
        default=0,
    )
    completed: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        index=True,
    )
    last_played_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )
    __table_args__ = (
        UniqueConstraint("user_id", "resource_id"),
        Index(
            "ix_user_playback_progress_user_last_played_at",
            "user_id",
            "last_played_at",
        ),
        Index(
            "ix_user_playback_progress_user_completed",
            "user_id",
            "completed",
        ),
    )

__all__ = [
    "User",
    "UserFavorite",
    "UserPlaybackProgress",
    "UserResourceHistory",
    "UserSession",
    "utcnow",
]
