"""Presentation-owned SQLAlchemy models."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ....platform.db import StateBase


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SitePresentation(StateBase):
    __tablename__ = "site_presentation"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    preset: Mapped[str] = mapped_column(String(20), default="custom")
    theme_tokens_json: Mapped[str] = mapped_column(Text, default="{}")
    navigation_json: Mapped[str] = mapped_column(Text, default="[]")
    home_blocks_json: Mapped[str] = mapped_column(Text, default="[]")
    config_revision: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default="1",
    )
    updated_by: Mapped[str] = mapped_column(String(100), default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )

    __table_args__ = (
        CheckConstraint(
            "preset IN ('software', 'tutorial', 'custom')",
            name="ck_site_presentation_preset",
        ),
    )


class SitePresentationRevision(StateBase):
    __tablename__ = "site_presentation_revisions"

    revision_id: Mapped[int] = mapped_column(primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, index=True)
    preset: Mapped[str] = mapped_column(String(20), default="custom")
    theme_tokens_json: Mapped[str] = mapped_column(Text, default="{}")
    navigation_json: Mapped[str] = mapped_column(Text, default="[]")
    home_blocks_json: Mapped[str] = mapped_column(Text, default="[]")
    summary: Mapped[str] = mapped_column(String(200), default="")
    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
    )


__all__ = ["SitePresentation", "SitePresentationRevision"]
