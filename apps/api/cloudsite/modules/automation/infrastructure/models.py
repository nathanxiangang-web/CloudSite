"""Automation-owned SQLAlchemy models."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ....platform.db import StateBase


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ParserCandidateTask(StateBase):
    __tablename__ = "parser_candidate_tasks"

    task_id: Mapped[str] = mapped_column(String(35), primary_key=True)
    resource_id: Mapped[str] = mapped_column(String(64), index=True)
    input_fingerprint: Mapped[str] = mapped_column(String(64))
    parser_version: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending", index=True
    )
    retry_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("resource_id", "input_fingerprint", "parser_version"),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_parser_candidate_tasks_status",
        ),
    )


__all__ = ["ParserCandidateTask"]
