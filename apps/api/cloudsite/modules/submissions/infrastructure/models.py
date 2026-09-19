"""Submissions-owned SQLAlchemy models."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ....platform.db import StateBase


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Submission(StateBase):
    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    resource_name: Mapped[str] = mapped_column(String(120))
    resource_type: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(Text, default="")
    source_url: Mapped[str] = mapped_column(String(1000), default="")
    download_url: Mapped[str] = mapped_column(String(2000), default="")
    copyright_note: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(
        String(20), default="pending", index=True
    )
    admin_note: Mapped[str] = mapped_column(Text, default="")
    reviewed_by: Mapped[str] = mapped_column(String(100), default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    published_resource_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


__all__ = ["Submission"]
