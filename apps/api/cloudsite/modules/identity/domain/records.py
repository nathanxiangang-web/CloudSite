"""Persistence-neutral records used by Identity application services."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class ResourceIdentityRecord:
    resource_id: str
    current_path: str | None
    root_mapping_id: int | None
    status: str
    first_seen_at: datetime
    last_seen_at: datetime
    last_name: str = ""
    last_extension: str = ""
    last_mime_type: str = ""
    last_size: int = 0
    last_modified_at: datetime | None = None
    provider_object_id: str | None = None
    content_hash: str | None = None
    identity_fingerprint: str | None = None
    fingerprint_version: int = 1
    created_from: str = "new_resource"
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ResourceIdentityHistoryRecord:
    resource_id: str
    path: str
    event_type: str
    first_observed_at: datetime
    last_observed_at: datetime
    from_path: str | None
    to_path: str | None
    cycle_id: int | None
    created_at: datetime


@dataclass(slots=True)
class FolderIdentityRecord:
    folder_id: str
    current_path: str
    root_mapping_id: int | None
    status: str
    first_seen_at: datetime
    last_seen_at: datetime
    last_name: str = ""
    identity_fingerprint: str | None = None
    fingerprint_version: int = 1
    created_from: str = "new_folder"
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class FolderIdentityHistoryRecord:
    folder_id: str
    path: str
    event_type: str
    from_path: str | None
    to_path: str | None
    cycle_id: int | None


__all__ = [
    "FolderIdentityHistoryRecord",
    "FolderIdentityRecord",
    "ResourceIdentityHistoryRecord",
    "ResourceIdentityRecord",
]
