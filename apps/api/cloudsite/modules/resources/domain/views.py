"""Persistence-neutral read models for Resources queries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class ParentSummaryView:
    id: str
    name: str

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name}


@dataclass(frozen=True, slots=True)
class ResourceSummaryView:
    id: str
    name: str
    parent_id: str | None
    content_type: str
    extension: str
    mime_type: str
    size: int
    modified_at: datetime | None
    status: str = "active"
    thumbnail: str = ""
    parent: ParentSummaryView | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "parent_id": self.parent_id,
            "content_type": self.content_type,
            "extension": self.extension,
            "mime_type": self.mime_type,
            "size": self.size,
            "modified_at": self.modified_at,
            "thumbnail": self.thumbnail,
        }
        if self.parent:
            payload["parent"] = self.parent.to_dict()
        return payload


@dataclass(frozen=True, slots=True)
class FolderSummaryView:
    id: str
    name: str
    parent_id: str | None
    content_type: str
    depth: int
    child_folder_count: int
    resource_count: int
    modified_at: datetime | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "parent_id": self.parent_id,
            "content_type": self.content_type,
            "depth": self.depth,
            "child_folder_count": self.child_folder_count,
            "resource_count": self.resource_count,
            "modified_at": self.modified_at,
        }




@dataclass(frozen=True, slots=True)
class AdminIndexCountsView:
    folders: int
    resources: int


@dataclass(frozen=True, slots=True)
class AdminIndexFolderView:
    id: str
    name: str
    parent_id: str | None
    content_type: str
    depth: int
    child_folder_count: int
    resource_count: int
    modified_at: datetime | None
    path: str
    root_mapping_id: int | None
    status: str
    indexed_at: datetime | None
    direct_resource_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "parent_id": self.parent_id,
            "content_type": self.content_type,
            "depth": self.depth,
            "child_folder_count": self.child_folder_count,
            "resource_count": self.resource_count,
            "modified_at": self.modified_at,
            "path": self.path,
            "root_mapping_id": self.root_mapping_id,
            "status": self.status,
            "indexed_at": self.indexed_at,
        }
        if self.direct_resource_count is not None:
            payload["direct_resource_count"] = self.direct_resource_count
        return payload


@dataclass(frozen=True, slots=True)
class CatalogResourceView:
    """Persistence-neutral resource state exposed to Catalog."""

    id: str
    name: str
    extension: str
    size: int
    status: str
    root_mapping_id: int | None
    content_type: str

@dataclass(frozen=True, slots=True)
class ParserResourceView:
    """Persistence-neutral resource input exposed to Automation."""

    id: str
    name: str
    path: str
    extension: str
    mime_type: str
    status: str
    content_type: str
    size: int
    indexed_at: datetime | None


@dataclass(frozen=True, slots=True)
class ResourceReferenceView:
    """Batch-safe resource metadata for cross-module references."""

    id: str
    name: str
    parent_id: str | None
    content_type: str
    extension: str
    mime_type: str
    size: int
    modified_at: datetime | None
    status: str
    root_mapping_id: int | None


@dataclass(frozen=True, slots=True)
class DiagnosticResourceView:
    """Internal delivery-diagnostic resource input."""

    id: str
    name: str
    path: str
    status: str
    root_mapping_id: int | None
    content_type: str


@dataclass(frozen=True, slots=True)
class ResourcePreviewView:
    """Internal preview input. Storage path is never serialized to API output."""

    id: str
    name: str
    path: str
    root_mapping_id: int | None
    extension: str
    mime_type: str
    size: int
    status: str


@dataclass(frozen=True, slots=True)
class ResourceDownloadView:
    """Internal download input. Storage path is never serialized to API output."""

    id: str
    path: str
    root_mapping_id: int
    status: str


@dataclass(frozen=True, slots=True)
class ResourcePageView:
    items: tuple[ResourceSummaryView, ...]
    total: int
    page: int
    page_size: int

    @property
    def total_pages(self) -> int:
        if not self.total:
            return 0
        return (self.total + self.page_size - 1) // self.page_size

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [item.to_dict() for item in self.items],
            "total": self.total,
            "page": self.page,
            "page_size": self.page_size,
            "total_pages": self.total_pages,
        }


@dataclass(frozen=True, slots=True)
class ResourceDetailView:
    resource: ResourceSummaryView
    breadcrumbs: tuple[ParentSummaryView, ...]
    related: tuple[ResourceSummaryView, ...]
    previous: ResourceSummaryView | None
    next: ResourceSummaryView | None

    def to_dict(self) -> dict[str, Any]:
        payload = self.resource.to_dict()
        payload.update(
            {
                "breadcrumbs": [item.to_dict() for item in self.breadcrumbs],
                "related": [item.to_dict() for item in self.related],
                "previous": self.previous.to_dict() if self.previous else None,
                "next": self.next.to_dict() if self.next else None,
            }
        )
        return payload


@dataclass(frozen=True, slots=True)
class FolderDetailView:
    folder: FolderSummaryView
    breadcrumbs: tuple[ParentSummaryView, ...]
    child_folders: tuple[FolderSummaryView, ...]
    resources: ResourcePageView

    def to_dict(self) -> dict[str, Any]:
        return {
            "folder": self.folder.to_dict(),
            "breadcrumbs": [item.to_dict() for item in self.breadcrumbs],
            "child_folders": [item.to_dict() for item in self.child_folders],
            "resources": self.resources.to_dict(),
        }


__all__ = [
    "DiagnosticResourceView",
    "AdminIndexFolderView",
    "AdminIndexCountsView",
    "CatalogResourceView",
    "FolderDetailView",
    "FolderSummaryView",
    "ParentSummaryView",
    "ParserResourceView",
    "ResourceDetailView",
    "ResourceDownloadView",
    "ResourcePageView",
    "ResourcePreviewView",
    "ResourceReferenceView",
    "ResourceSummaryView",
]
