"""C3 Catalog metadata request and response models for the admin HTTP boundary.

Strict schemas for tags, tag assignments, typed entry relations, and immutable
revision browsing. All identifiers use stable string IDs (prefix + 32 hex chars,
35 characters total) matching the String(35) columns on the C3 metadata tables.

Extra fields are forbidden on every request model so callers cannot sneak in
arbitrary URLs, HTML, or unexpected keys. Only stable string IDs are accepted;
no endpoint in this module accepts upstream/mirror URLs or free-form HTML.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ---- Stable ID patterns (prefix + 32 chars, 35 total) ----

_TAG_ID_PATTERN = r"^ct_[A-Za-z0-9_-]{32}$"
_RELATION_ID_PATTERN = r"^cx_[A-Za-z0-9_-]{32}$"
_REVISION_ID_PATTERN = r"^cv_[A-Za-z0-9_-]{32}$"
_ENTRY_ID_PATTERN = r"^ce_[A-Za-z0-9_-]{32}$"
_RELEASE_ID_PATTERN = r"^cr_[A-Za-z0-9_-]{32}$"
_ASSET_ID_PATTERN = r"^ca_[A-Za-z0-9_-]{32}$"

_TAG_SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
_TAG_TARGET_TYPE = Literal["entry", "release", "asset"]


# ---- Tag request schemas ----

class CatalogTagCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(pattern=_TAG_SLUG_PATTERN, max_length=60)
    display_name: str = Field(min_length=1, max_length=100)


class CatalogTagUpdateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str | None = Field(default=None, pattern=_TAG_SLUG_PATTERN, max_length=60)
    display_name: str | None = Field(default=None, min_length=1, max_length=100)


# ---- Tag assignment request schemas ----

class CatalogTagAssignmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tag_id: str = Field(pattern=_TAG_ID_PATTERN)
    target_type: _TAG_TARGET_TYPE
    target_id: str = Field(min_length=1, max_length=35)


# ---- Relation request schemas ----

class CatalogRelationCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_entry_id: str = Field(pattern=_ENTRY_ID_PATTERN)
    to_entry_id: str = Field(pattern=_ENTRY_ID_PATTERN)
    relation_type: str = Field(min_length=1, max_length=40)
    note: str = Field(default="", max_length=2000)


# ---- Response schemas ----

class CatalogTagSummary(BaseModel):
    tag_id: str
    slug: str
    display_name: str
    created_at: datetime
    updated_at: datetime


class CatalogTagAssignmentSummary(BaseModel):
    tag_id: str
    target_type: str
    target_id: str
    created_at: datetime


class CatalogRelationSummary(BaseModel):
    relation_id: str
    from_entry_id: str
    to_entry_id: str
    relation_type: str
    note: str = ""
    created_at: datetime


class CatalogRevisionSummary(BaseModel):
    revision_id: str
    target_type: str
    target_id: str
    action: str
    actor: str
    source: str = "admin"
    base_revision: int | None = None
    resulting_revision: int | None = None
    summary: str = ""
    before: dict | None = None
    after: dict | None = None
    diff: dict | None = None
    payload: dict | None = None
    created_at: datetime


class CatalogRevisionListOutput(BaseModel):
    items: list[CatalogRevisionSummary]
    page: int
    page_size: int
    total: int
    total_pages: int
