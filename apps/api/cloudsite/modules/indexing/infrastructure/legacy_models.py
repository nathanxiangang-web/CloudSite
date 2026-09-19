"""Indexing-owned ORM declarations for the frozen legacy sync tables.

These tables are compatibility state for the 1.x rolling-sync pipeline. New
indexing work must not write new features against them; they remain owned here
until the legacy pipeline is retired.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ....platform.db import IndexBase


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SyncRun(IndexBase):
    __tablename__ = "sync_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    sync_type: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), index=True)
    folders_scanned: Mapped[int] = mapped_column(Integer, default=0)
    resources_scanned: Mapped[int] = mapped_column(Integer, default=0)
    added_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    removed_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str] = mapped_column(Text, default="")
    current_path: Mapped[str] = mapped_column(String(1500), default="")
    roots_total: Mapped[int] = mapped_column(Integer, default=0)
    roots_completed: Mapped[int] = mapped_column(Integer, default=0)
    roots_failed: Mapped[int] = mapped_column(Integer, default=0)
    list_requests: Mapped[int] = mapped_column(Integer, default=0)
    trigger_source: Mapped[str] = mapped_column(String(20), default="auto")
    target_paths_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    force_refresh_paths_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    renamed_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_verified_count: Mapped[int] = mapped_column(Integer, default=0)
    refresh_true_count: Mapped[int] = mapped_column(Integer, default=0)
    auto_interrupted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    auto_resumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SyncRootResult(IndexBase):
    __tablename__ = "sync_root_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    sync_run_id: Mapped[int] = mapped_column(ForeignKey("sync_runs.id", ondelete="CASCADE"), index=True)
    root_mapping_id: Mapped[int] = mapped_column(Integer, index=True)
    root_path: Mapped[str] = mapped_column(String(1500))
    status: Mapped[str] = mapped_column(String(30), index=True)
    folders_scanned: Mapped[int] = mapped_column(Integer, default=0)
    resources_scanned: Mapped[int] = mapped_column(Integer, default=0)
    added_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    removed_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str] = mapped_column(Text, default="")
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("sync_run_id", "root_mapping_id"),)


class SyncChange(IndexBase):
    __tablename__ = "sync_changes"
    id: Mapped[int] = mapped_column(primary_key=True)
    sync_run_id: Mapped[int] = mapped_column(ForeignKey("sync_runs.id", ondelete="CASCADE"), index=True)
    object_type: Mapped[str] = mapped_column(String(20))
    object_id: Mapped[str] = mapped_column(String(64))
    change_type: Mapped[str] = mapped_column(String(20))
    old_path: Mapped[str | None] = mapped_column(String(1500), nullable=True)
    new_path: Mapped[str | None] = mapped_column(String(1500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("sync_run_id", "object_type", "object_id", "change_type"),)


class SyncCycle(IndexBase):
    __tablename__ = "sync_cycles"
    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_type: Mapped[str] = mapped_column(String(30), default="normal", index=True)
    status: Mapped[str] = mapped_column(String(30), default="planned", index=True)
    anchor_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    planned_folder_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_folder_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_folder_count: Mapped[int] = mapped_column(Integer, default=0)
    carry_over_count: Mapped[int] = mapped_column(Integer, default=0)
    windows_total: Mapped[int] = mapped_column(Integer, default=4)
    windows_completed: Mapped[int] = mapped_column(Integer, default=0)
    alist_list_requests: Mapped[int] = mapped_column(Integer, default=0)
    changed_scope_count: Mapped[int] = mapped_column(Integer, default=0)
    unchanged_scope_count: Mapped[int] = mapped_column(Integer, default=0)
    fts_rebuilt_count: Mapped[int] = mapped_column(Integer, default=0)
    renamed_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_verified_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SyncCycleItem(IndexBase):
    __tablename__ = "sync_cycle_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("sync_cycles.id", ondelete="CASCADE"), index=True)
    folder_id: Mapped[str] = mapped_column(String(64), index=True)
    folder_path: Mapped[str] = mapped_column(String(1500))
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0, index=True)
    window_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    __table_args__ = (UniqueConstraint("cycle_id", "folder_id"),)


class FolderScanState(IndexBase):
    __tablename__ = "folder_scan_state"
    folder_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    path: Mapped[str] = mapped_column(String(1500), index=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_verified_cycle_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(64), default="")
    fingerprint_version: Mapped[int] = mapped_column(Integer, default=1)
    last_scan_result: Mapped[str] = mapped_column(String(30), default="never")
    last_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


__all__ = [
    "SyncRun",
    "SyncRootResult",
    "SyncChange",
    "SyncCycle",
    "SyncCycleItem",
    "FolderScanState",
]
