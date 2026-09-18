"""Identity-owned SQLAlchemy models.

The tables and columns are intentionally identical to the legacy definitions
that previously lived in cloudsite.models.  They still use the shared platform
StateBase/IndexBase so database metadata and migrations remain compatible.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ....platform.db import IndexBase, StateBase


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ResourceIdentity(StateBase):
    __tablename__ = "resource_identities"

    resource_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    current_path: Mapped[str | None] = mapped_column(String(1500), nullable=True, index=True)
    root_mapping_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_name: Mapped[str] = mapped_column(String(500), default="")
    last_extension: Mapped[str] = mapped_column(String(40), default="")
    last_mime_type: Mapped[str] = mapped_column(String(200), default="")
    last_size: Mapped[int] = mapped_column(BigInteger, default=0)
    last_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_object_id: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)
    content_hash: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    identity_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    fingerprint_version: Mapped[int] = mapped_column(Integer, default=1)
    created_from: Mapped[str] = mapped_column(String(30), default="new_resource")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ResourceIdentityHistory(StateBase):
    __tablename__ = "resource_identity_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[str] = mapped_column(
        ForeignKey("resource_identities.resource_id", ondelete="RESTRICT"), index=True
    )
    path: Mapped[str] = mapped_column(String(1500), index=True)
    event_type: Mapped[str] = mapped_column(String(30), index=True)
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    from_path: Mapped[str | None] = mapped_column(String(1500), nullable=True)
    to_path: Mapped[str | None] = mapped_column(String(1500), nullable=True)
    cycle_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FolderIdentity(StateBase):
    __tablename__ = "folder_identities"

    folder_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    current_path: Mapped[str] = mapped_column(String(1500), index=True)
    root_mapping_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_name: Mapped[str] = mapped_column(String(500), default="")
    identity_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    fingerprint_version: Mapped[int] = mapped_column(Integer, default=1)
    created_from: Mapped[str] = mapped_column(String(30), default="new_folder")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class FolderIdentityHistory(StateBase):
    __tablename__ = "folder_identity_histories"

    id: Mapped[int] = mapped_column(primary_key=True)
    folder_id: Mapped[str] = mapped_column(
        ForeignKey("folder_identities.folder_id", ondelete="RESTRICT"), index=True
    )
    path: Mapped[str] = mapped_column(String(1500), index=True)
    event_type: Mapped[str] = mapped_column(String(30), index=True)
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    from_path: Mapped[str | None] = mapped_column(String(1500), nullable=True)
    to_path: Mapped[str | None] = mapped_column(String(1500), nullable=True)
    cycle_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ResourceIdentityCandidate(IndexBase):
    __tablename__ = "resource_identity_candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    observed_path: Mapped[str] = mapped_column(String(1500), index=True)
    observed_name: Mapped[str] = mapped_column(String(500), default="")
    observed_parent_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    root_mapping_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    content_type: Mapped[str] = mapped_column(String(40), default="file")
    matched_resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    candidate_resource_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    match_type: Mapped[str] = mapped_column(String(40), default="fingerprint")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    extension: Mapped[str] = mapped_column(String(40), default="")
    mime_type: Mapped[str] = mapped_column(String(200), default="")
    thumbnail: Mapped[str] = mapped_column(Text, default="")
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint("cycle_id", "observed_path"),)


__all__ = [
    "FolderIdentity",
    "FolderIdentityHistory",
    "ResourceIdentity",
    "ResourceIdentityCandidate",
    "ResourceIdentityHistory",
]
