"""Publication-safe Resources views for cross-module consumers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .views import FolderSummaryView


@dataclass(frozen=True, slots=True)
class PublicationResourceView:
    id: str
    name: str
    path: str
    parent_id: str | None
    content_type: str
    root_mapping_id: int
    extension: str
    mime_type: str
    size: int
    modified_at: datetime | None
    thumbnail: str = ""

    def to_public_dict(self) -> dict[str, Any]:
        return {
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


@dataclass(frozen=True, slots=True)
class PublicationFolderView:
    folder: FolderSummaryView
    root_mapping_id: int
    folders: tuple[FolderSummaryView, ...]
    resources: tuple[PublicationResourceView, ...]

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "folder": self.folder.to_dict(),
            "folders": [item.to_dict() for item in self.folders],
            "resources": [
                item.to_public_dict()
                for item in self.resources
            ],
        }


__all__ = [
    "PublicationFolderView",
    "PublicationResourceView",
]
