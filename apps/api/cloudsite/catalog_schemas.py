"""C1 Catalog request and response models for the HTTP boundary.

Domain exceptions live in ``services/catalog.py``. Keeping them out of this
module prevents the HTTP layer from catching a different class than the
application layer raises.

All identifiers use the reviewed C1 stable-ID contract: a 3-character prefix
followed by 32 hex characters (35 characters total), matching the String(35)
columns on CatalogEntry, CatalogRelease, CatalogAsset, and CatalogLocation.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ---- Shared field patterns ----

_CONTENT_TYPE_PATTERN = r"^[a-z][a-z0-9_-]{1,39}$"
_ENTRY_ID_PATTERN = r"^ce_[A-Za-z0-9_-]{32}$"
_ASSET_ID_PATTERN = r"^ca_[A-Za-z0-9_-]{32}$"
_RESOURCE_ID_PATTERN = r"^r_[A-Za-z0-9_-]{32}$"


# ---- Request schemas ----

class CatalogEntryCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=500)
    description: str = Field(default="", max_length=4000)
    content_type: str = Field(pattern=_CONTENT_TYPE_PATTERN)
    slug: str | None = Field(default=None, min_length=1, max_length=160)


class CatalogEntryUpdateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    slug: str | None = Field(default=None, min_length=1, max_length=160)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=4000)
    content_type: str | None = Field(default=None, pattern=_CONTENT_TYPE_PATTERN)
    cover_resource_id: str | None = Field(default=None, max_length=64)
    status: Literal["draft", "published", "archived", "disabled"] | None = None
    sort_order: int | None = None


class CatalogEntryPublishInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)


class CatalogLocationBindInput(BaseModel):
    """Bind an indexed resource as a download location for a catalog asset.

    Only stable resource_id references are accepted; arbitrary upstream or
    mirror URLs are never accepted. Extra fields are forbidden so callers
    cannot sneak in url/upstream_url/mirror_url fields. The resource_id must
    exist in index.db (enforced by the service layer).
    """

    model_config = ConfigDict(extra="forbid")

    asset_id: str = Field(pattern=_ASSET_ID_PATTERN)
    resource_id: str = Field(pattern=_RESOURCE_ID_PATTERN)
    label: str = Field(default="", max_length=100)
    is_primary: bool = False


# ---- Response schemas ----

class CatalogLocationSummary(BaseModel):
    location_id: str
    asset_id: str
    display_name: str
    sort_order: int
    available: bool
    content_type: str = ""
    extension: str = ""
    size: int = 0


class CatalogEntrySummary(BaseModel):
    entry_id: str
    title: str
    summary: str
    content_type: str
    status: Literal["draft", "published", "archived", "disabled"]
    revision: int
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None = None


class CatalogEntryDetail(CatalogEntrySummary):
    description: str = ""
    locations: list[CatalogLocationSummary] = Field(default_factory=list)


class CatalogEntryListOutput(BaseModel):
    items: list[CatalogEntrySummary]
    page: int
    page_size: int
    total: int
    total_pages: int


class CatalogPreviewOutput(BaseModel):
    entry: CatalogEntryDetail
    previewable: bool
    reason: str = ""
