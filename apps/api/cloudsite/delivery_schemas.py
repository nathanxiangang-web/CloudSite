"""T2 delivery package request/response models.

Strict schema: all request models extra=forbid.
Package ID uses dp_ prefix + 32 hex (35 chars).
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

_PACKAGE_ID_PATTERN = r"^dp_[A-Za-z0-9_-]{32}$"


class CreatePackageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    project_note: str = ""
    access_code: str | None = None
    expires_at: datetime | None = None


class AddItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str | None = None
    resource_id: str | None = None
    display_name: str = ""
    note: str = ""
    sort_order: int = 0


class PackageSummaryResponse(BaseModel):
    package_id: str
    name: str
    project_note: str
    revision: int
    creator_user_id: int | None
    status: str
    expires_at: datetime | None
    published_at: datetime | None
    item_count: int
    created_at: datetime
    updated_at: datetime


class PackageListResponse(BaseModel):
    items: list[PackageSummaryResponse]
    total: int
    page: int
    page_size: int


class ItemResponse(BaseModel):
    item_id: int
    package_id: str
    asset_id: str | None
    resource_id: str | None
    display_name: str
    bound_checksum: str | None
    bound_checksum_algorithm: str | None
    bound_size: int | None
    sort_order: int
    note: str
    changed: bool


class PackageDetailResponse(BaseModel):
    package: PackageSummaryResponse
    items: list[ItemResponse]


class ExportResponse(BaseModel):
    data: dict


class VerifyAccessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    access_code: str | None = None


class DeliveryFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(min_length=1, max_length=50)
    message: str = ""