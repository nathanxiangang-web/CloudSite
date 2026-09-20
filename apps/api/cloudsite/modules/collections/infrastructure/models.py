"""Collections-owned SQLAlchemy models."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ....platform.db import StateBase


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class CollectionItem(StateBase):
    __tablename__ = "collection_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    collection_id: Mapped[int] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), index=True
    )
    resource_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    item_type: Mapped[str] = mapped_column(
        String(20), default="resource", server_default="resource", index=True
    )
    catalog_entry_id: Mapped[str | None] = mapped_column(
        String(35), nullable=True, index=True
    )
    note: Mapped[str] = mapped_column(Text, default="", server_default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    __table_args__ = (
        UniqueConstraint("collection_id", "resource_id"),
        UniqueConstraint("collection_id", "catalog_entry_id"),
        CheckConstraint("item_type IN ('resource', 'catalog_entry')"),
    )


__all__ = ["Collection", "CollectionItem"]
