"""Automation-owned SQLAlchemy models."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, Float, Index, Integer, String, Text, UniqueConstraint
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



class CatalogSuggestion(StateBase):
    """Automation-owned advisory catalog suggestion state."""

    __tablename__ = "catalog_suggestions"

    suggestion_id: Mapped[str] = mapped_column(String(35), primary_key=True)
    source_file_id: Mapped[str] = mapped_column(String(64), index=True)
    file_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    parser_version: Mapped[str] = mapped_column(String(20))
    suggestion_kind: Mapped[str] = mapped_column(String(30), index=True)
    target_entry_id: Mapped[str | None] = mapped_column(String(35), nullable=True, index=True)
    target_release_id: Mapped[str | None] = mapped_column(String(35), nullable=True, index=True)
    target_asset_id: Mapped[str | None] = mapped_column(String(35), nullable=True, index=True)
    suggested_fields_json: Mapped[str] = mapped_column(Text, default="{}")
    evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    reviewed_by: Mapped[str] = mapped_column(String(100), default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_revision_id: Mapped[str | None] = mapped_column(String(35), nullable=True)
    reject_reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "source_file_id",
            "file_fingerprint",
            "parser_version",
            "suggestion_kind",
            name="ux_catalog_suggestions_idempotent",
        ),
        Index(
            "ix_catalog_suggestions_kind_status",
            "suggestion_kind",
            "status",
        ),
        CheckConstraint(
            "suggestion_kind IN ('new_entry', 'new_release', 'asset', 'candidate_duplicate', 'conflict')",
            name="ck_catalog_suggestions_kind",
        ),
        CheckConstraint(
            "status IN ('pending', 'reviewed', 'applied', 'rejected')",
            name="ck_catalog_suggestions_status",
        ),
    )


__all__ = ["ParserCandidateTask", "CatalogSuggestion"]
