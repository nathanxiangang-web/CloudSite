"""Resources-owned SQLAlchemy models.

These declarations are intentionally identical to the legacy definitions that
previously lived in cloudsite.models. They continue to use the shared platform
StateBase/IndexBase metadata so existing databases and migrations remain
compatible.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ....platform.db import IndexBase, StateBase


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DownloadRateLimit(StateBase):
    __tablename__ = "download_rate_limits"

    id: Mapped[int] = mapped_column(primary_key=True)
    ip_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    recent_hits_json: Mapped[str] = mapped_column(Text, default="[]")
    blocked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, index=True
    )


class Folder(IndexBase):
    __tablename__ = "folders"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(500), index=True)
    path: Mapped[str] = mapped_column(String(1500))
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
    __table_args__ = (UniqueConstraint("root_mapping_id", "path"),)


class Resource(IndexBase):
    __tablename__ = "resources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(500), index=True)
    path: Mapped[str] = mapped_column(String(1500))
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
    __table_args__ = (UniqueConstraint("root_mapping_id", "path"),)


__all__ = ["DownloadRateLimit", "Folder", "Resource"]
