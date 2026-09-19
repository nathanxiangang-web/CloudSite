"""Providers-owned SQLAlchemy models.

These declarations are intentionally identical to their legacy cloudsite.models
definitions and continue to use the shared platform metadata. Existing database
schema and migration history remain unchanged.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ....platform.db import IndexBase, StateBase


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AListConnection(StateBase):
    __tablename__ = "alist_connections"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), default="默认连接")
    base_url: Mapped[str] = mapped_column(String(500), default="")
    base_path: Mapped[str] = mapped_column(String(1000), default="/")
    username: Mapped[str] = mapped_column(String(200), default="")
    password_ciphertext: Mapped[str] = mapped_column(Text, default="")
    remember_credentials: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    last_test_status: Mapped[str] = mapped_column(String(40), default="untested")
    last_test_message: Mapped[str] = mapped_column(Text, default="")
    last_test_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    provider_type: Mapped[str] = mapped_column(String(40), default="generic_alist")
    provider_capability_version: Mapped[int] = mapped_column(Integer, default=1)
    provider_capabilities_json: Mapped[str] = mapped_column(Text, default="")
    capabilities_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ContentRootMapping(StateBase):
    __tablename__ = "content_root_mappings"

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    content_type: Mapped[str] = mapped_column(String(40), index=True)
    display_name: Mapped[str] = mapped_column(String(100))
    alist_path: Mapped[str] = mapped_column(String(1000))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    home_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    __table_args__ = (UniqueConstraint("connection_id", "alist_path"),)


class ProviderSyncState(IndexBase):
    __tablename__ = "provider_sync_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(Integer, index=True)
    root_mapping_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    strategy: Mapped[str] = mapped_column(String(30), default="rolling")
    cursor: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cursor_version: Mapped[int] = mapped_column(Integer, default=0)
    provider_generation: Mapped[str] = mapped_column(String(100), default="")
    last_delta_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_full_verify_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(30), default="idle")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    __table_args__ = (UniqueConstraint("connection_id", "root_mapping_id"),)


__all__ = ["AListConnection", "ContentRootMapping", "ProviderSyncState"]
