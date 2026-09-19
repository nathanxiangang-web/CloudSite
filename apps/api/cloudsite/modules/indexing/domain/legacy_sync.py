"""Persistence-neutral views over the frozen legacy sync tables."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class LegacySyncRunView:
    id: int
    status: str
    sync_type: str = ""
    folders_scanned: int = 0
    resources_scanned: int = 0
    added_count: int = 0
    updated_count: int = 0
    removed_count: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int = 0
    error_message: str = ""
    current_path: str = ""
    roots_total: int = 0
    roots_completed: int = 0
    roots_failed: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "sync_type": self.sync_type,
            "status": self.status,
            "folders_scanned": self.folders_scanned,
            "resources_scanned": self.resources_scanned,
            "added_count": self.added_count,
            "updated_count": self.updated_count,
            "removed_count": self.removed_count,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "error_message": self.error_message,
            "current_path": self.current_path,
            "roots_total": self.roots_total,
            "roots_completed": self.roots_completed,
            "roots_failed": self.roots_failed,
        }


@dataclass(frozen=True, slots=True)
class LegacySyncChangeView:
    id: int
    object_type: str
    object_id: str
    change_type: str
    old_path: str | None = None
    new_path: str | None = None
    created_at: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "object_type": self.object_type,
            "object_id": self.object_id,
            "change_type": self.change_type,
            "old_path": self.old_path,
            "new_path": self.new_path,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class LegacySyncChangePage:
    items: tuple[LegacySyncChangeView, ...]
    has_more: bool


__all__ = [
    "LegacySyncRunView",
    "LegacySyncChangeView",
    "LegacySyncChangePage",
]
