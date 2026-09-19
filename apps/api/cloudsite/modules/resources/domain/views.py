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


__all__ = [
    "FolderSummaryView",
    "ParentSummaryView",
    "ResourcePageView",
    "ResourceSummaryView",
]
