from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class AListInput(BaseModel):
    base_url: str = Field(min_length=4, max_length=500)
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(default="", max_length=500)
    remember_credentials: bool = True


class RootMappingInput(BaseModel):
    content_type: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,39}$")
    display_name: str = Field(min_length=1, max_length=100)
    alist_path: str = Field(min_length=1, max_length=1000)
    enabled: bool = True
    sort_order: int = 0


class SiteInput(BaseModel):
    site_name: str = Field(min_length=1, max_length=100)
    home_title: str = Field(min_length=1, max_length=200)
    description: str = Field(max_length=500)


class SyncInput(BaseModel):
    full: bool = False
    force: bool = False


class SystemInput(BaseModel):
    automatic_sync: bool = False
    sync_interval_minutes: Literal[180, 360, 720, 1440] = 360
    sync_on_startup: bool = False


class CollectionInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=1000)
    cover: str = Field(default="", max_length=1000)
    status: str = Field(default="active", pattern=r"^(active|hidden)$")
    visible_on_home: bool = True
    sort_order: int = 0


class CollectionItemsInput(BaseModel):
    resource_ids: list[str] = Field(default_factory=list, max_length=200)


class ShareInput(BaseModel):
    object_type: str = Field(pattern=r"^(resource|folder|collection)$")
    object_id: str = Field(min_length=1, max_length=64)
    title: str = Field(default="", max_length=200)
    access_mode: Literal["code", "direct"] = "code"
    duration: Literal["5m", "1h", "6h", "24h", "7d", "permanent"] = "24h"


class ShareUpdate(BaseModel):
    enabled: bool | None = None
    duration: Literal["5m", "1h", "6h", "24h", "7d", "permanent"] | None = None
    action: Literal["cancel", "restore", "reset_code", "upgrade"] | None = None


class ShareVerifyInput(BaseModel):
    code: str = Field(min_length=1, max_length=16)
    captcha_token: str | None = Field(default=None, max_length=2000)


class AdminLoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=500)


class UserRegisterInput(BaseModel):
    username: str = Field(max_length=200)
    password: str = Field(max_length=200)
    password_confirm: str = Field(max_length=200)


class UserLoginInput(BaseModel):
    username: str = Field(max_length=200)
    password: str = Field(max_length=200)


class UserPasswordChangeInput(BaseModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(max_length=200)
    new_password_confirm: str = Field(max_length=200)


class UserStatusInput(BaseModel):
    status: Literal["active", "disabled"]


class AdminUserCreateInput(BaseModel):
    username: str = Field(max_length=200)
    password: str = Field(max_length=200)
    password_confirm: str = Field(max_length=200)


class AdminUserUpdateInput(BaseModel):
    username: str = Field(max_length=200)


class AdminPasswordResetInput(BaseModel):
    new_password: str = Field(max_length=200)
    new_password_confirm: str = Field(max_length=200)


class DownloadDiagnosticInput(BaseModel):
    resource_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    force_refresh: bool = True


class ParentSummary(BaseModel):
    id: str
    name: str


class BreadcrumbItem(BaseModel):
    id: str
    name: str


class ResourceSummary(BaseModel):
    id: str
    name: str
    parent_id: str | None
    parent: ParentSummary | None = None
    content_type: str
    extension: str
    mime_type: str
    size: int
    modified_at: datetime | None
    thumbnail: str = ""


class PreviewCapability(BaseModel):
    preview_type: str
    can_preview: bool
    preview_mode: str
    browser_native: bool = False
    mime_type: str = ""
    extension: str = ""
    reason: str = ""
    gateway_url: str = ""
    can_download: bool


class ResourceDetailOutput(ResourceSummary):
    breadcrumbs: list[BreadcrumbItem]
    related: list[ResourceSummary]
    capabilities: PreviewCapability
    previous: ResourceSummary | None = None
    next: ResourceSummary | None = None


class TextPreviewOutput(BaseModel):
    content: str
    truncated: bool
    size: int
    encoding: str
    preview_type: str


class FolderSummary(BaseModel):
    id: str
    name: str
    parent_id: str | None
    content_type: str
    depth: int
    child_folder_count: int
    resource_count: int
    modified_at: datetime | None


class ResourcePageOutput(BaseModel):
    items: list[ResourceSummary]
    page: int
    page_size: int
    total: int
    total_pages: int


class FolderListOutput(BaseModel):
    items: list[FolderSummary]


class FolderDetailOutput(BaseModel):
    folder: FolderSummary
    breadcrumbs: list[BreadcrumbItem]
    child_folders: list[FolderSummary]
    resources: ResourcePageOutput


class ContentRootSummary(BaseModel):
    id: int
    content_type: str
    display_name: str
    resource_count: int
    folder_count: int
    sort_order: int


class ContentRootListOutput(BaseModel):
    items: list[ContentRootSummary]


class SearchResultItem(BaseModel):
    id: str
    object_type: str
    name: str
    content_type: str
    extension: str = ""
    size: int | None = None
    modified_at: datetime | None = None
    parent: ParentSummary | None = None
    breadcrumbs: list[BreadcrumbItem] = Field(default_factory=list)
    thumbnail: str = ""
    child_folder_count: int = 0
    resource_count: int = 0
    match_type: str


class SearchOutput(BaseModel):
    query: str
    filters: dict[str, str | None]
    items: list[SearchResultItem]
    page: int
    page_size: int
    total: int
    total_pages: int
