"""C1 Catalog schema module: narrow request/response models and service contract errors.

Schemas and routers for the Catalog HTTP contract live in dedicated files so the
C1 surface stays self-contained. Service-level exceptions are declared here so
both the routers and the parallel-developed ``services/catalog.py`` share one
error contract without duplicating business logic. The routers translate these
errors to HTTP responses; business validation stays in the service module.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# ---- Service contract errors ----
# Raised by services/catalog.py, translated to HTTP by the routers.

class CatalogError(Exception):
    """Base error for Catalog service failures."""


class CatalogEntryNotFound(CatalogError):
    """Raised when a catalog entry does not exist."""


class CatalogRevisionConflict(CatalogError):
    """Raised when expected_revision does not match the stored revision."""


class CatalogLocationUnavailable(CatalogError):
    """Raised when a bound asset is not available in the current publication scope."""


class CatalogEntryNotPreviewable(CatalogError):
    """Raised when an entry cannot be previewed in its current state."""


# ---- Shared field patterns ----

_CONTENT_TYPE_PATTERN = r"^[a-z][a-z0-9_-]{1,39}$"
_ASSET_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"


# ---- Request schemas ----

class CatalogEntryCreateInput(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=500)
    description: str = Field(default="", max_length=4000)
    content_type: str = Field(pattern=_CONTENT_TYPE_PATTERN)


class CatalogEntryUpdateInput(BaseModel):
    expected_revision: int = Field(ge=0)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=4000)
    content_type: str | None = Field(default=None, pattern=_CONTENT_TYPE_PATTERN)


class CatalogLocationBindInput(BaseModel):
    asset_id: str = Field(min_length=1, max_length=64, pattern=_ASSET_ID_PATTERN)
    display_name: str = Field(default="", max_length=200)
    sort_order: int = 0


# ---- Response schemas ----

class CatalogLocationSummary(BaseModel):
    id: int
    asset_id: str
    display_name: str
    sort_order: int
    available: bool
    content_type: str = ""
    extension: str = ""
    size: int = 0


class CatalogEntrySummary(BaseModel):
    id: int
    title: str
    summary: str
    content_type: str
    status: Literal["draft", "published"]
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
