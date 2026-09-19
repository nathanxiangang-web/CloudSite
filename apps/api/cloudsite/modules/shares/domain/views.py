"""Persistence-neutral Shares read models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


ShareStatus = Literal[
    "active",
    "cancelled",
    "expired",
    "invalid_target",
    "migration_pending",
]


@dataclass(frozen=True, slots=True)
class ShareView:
    token: str
    creator_user_id: int | None
    object_type: str
    object_id: str
    title: str
    enabled: bool
    access_mode: str
    code_hash: str | None
    code_version: int
    expires_at: datetime | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    access_count: int
    view_count: int
    download_count: int
    last_accessed_at: datetime | None
    last_downloaded_at: datetime | None
    created_at: datetime
    updated_at: datetime


__all__ = ["ShareStatus", "ShareView"]
