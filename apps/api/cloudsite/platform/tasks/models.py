from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from ..db.base import StateBase


class TaskORM(StateBase):
    __tablename__ = 'platform_tasks'

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    queue: Mapped[str] = mapped_column(String(64), nullable=False, default='default', index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default='pending', index=True)
    priority: Mapped[int] = mapped_column(nullable=False, default=5)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    parent_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    root_task_id: Mapped[str] = mapped_column(String(64), nullable=False)
    max_attempts: Mapped[int] = mapped_column(nullable=False, default=5)
    attempt_count: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    retry_at: Mapped[datetime | None] = mapped_column(nullable=True, index=True)
    last_error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index('ix_platform_tasks_queue_status', 'queue', 'status'),
        Index('ix_platform_tasks_status_retry', 'status', 'retry_at'),
        Index('ix_platform_tasks_dedupe_status', 'dedupe_key', 'status'),
    )


__all__ = ['TaskORM']
