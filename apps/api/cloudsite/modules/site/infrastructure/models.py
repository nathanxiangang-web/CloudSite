"""Site-owned persistence model."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ....platform.db import StateBase


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SiteSettings(StateBase):
    __tablename__ = "site_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    site_name: Mapped[str] = mapped_column(String(100), default="CloudSite")
    home_title: Mapped[str] = mapped_column(
        String(200),
        default="把网盘变成好看的资源网站",
    )
    description: Mapped[str] = mapped_column(
        String(500),
        default="软件、图库、视频、教程和文件，集中整理，轻松搜索，便捷分享",
    )
    hero_subtitle: Mapped[str] = mapped_column(String(200), default="")
    footer_text: Mapped[str] = mapped_column(String(300), default="")
    submission_email: Mapped[str] = mapped_column(
        String(200),
        default="nathxo@outlook.com",
    )
    github_url: Mapped[str] = mapped_column(String(300), default="")
    registration_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    default_share_duration: Mapped[str] = mapped_column(
        String(20),
        default="24h",
    )
    share_image_name: Mapped[str] = mapped_column(String(255), default="")
    recent_limit: Mapped[int] = mapped_column(Integer, default=6)
    popular_limit: Mapped[int] = mapped_column(Integer, default=6)
    collection_limit: Mapped[int] = mapped_column(Integer, default=4)
    popular_strategy: Mapped[str] = mapped_column(
        String(20),
        default="recent",
        server_default="recent",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )


__all__ = ["SiteSettings"]
