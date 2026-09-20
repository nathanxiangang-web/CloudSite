from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class ProviderChangeType(str, Enum):
    CREATE = 'create'
    UPDATE = 'update'
    DELETE = 'delete'
    RENAME = 'rename'
    MOVE = 'move'
    DIRECTORY_DIRTY = 'directory_dirty'


class ProviderChangeSource(str, Enum):
    CLOUDSITE = 'cloudsite'
    PROVIDER_DELTA = 'provider_delta'
    PROVIDER_WEBHOOK = 'provider_webhook'
    VERIFICATION = 'verification'
    MANUAL = 'manual'


@dataclass(slots=True)
class ProviderChange:
    """A single observed provider-level change event (V2 doc section 25).

    Unified change object for both CloudSite-known changes and externally
    detected changes.  Consumed by the incremental apply pipeline to decide
    whether a targeted scan/reconcile is needed or a direct apply is safe.
    """

    change_type: ProviderChangeType
    root_mapping_id: int
    path: str
    is_dir: bool = False
    provider_object_id: str | None = None
    resource_id: str | None = None
    old_path: str | None = None
    source: ProviderChangeSource = ProviderChangeSource.VERIFICATION
    observed_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def is_deletion(self) -> bool:
        return self.change_type is ProviderChangeType.DELETE

    @property
    def is_rename_or_move(self) -> bool:
        return self.change_type in (
            ProviderChangeType.RENAME,
            ProviderChangeType.MOVE,
        )

    @property
    def is_directory_dirty(self) -> bool:
        return self.change_type is ProviderChangeType.DIRECTORY_DIRTY

    @property
    def requires_targeted_scan(self) -> bool:
        """Directory-dirty events need a targeted re-scan; others can be
        applied directly when identity is known."""
        return self.change_type is ProviderChangeType.DIRECTORY_DIRTY

    @property
    def is_cloudsite_known(self) -> bool:
        """Change originated from a CloudSite-initiated operation."""
        return self.source is ProviderChangeSource.CLOUDSITE

    def to_dict(self) -> dict[str, str | int | bool | None]:
        """Serialize to a plain dict for logging / persistence."""
        return {
            'change_type': self.change_type.value,
            'root_mapping_id': self.root_mapping_id,
            'path': self.path,
            'is_dir': self.is_dir,
            'provider_object_id': self.provider_object_id,
            'resource_id': self.resource_id,
            'old_path': self.old_path,
            'source': self.source.value,
            'observed_at': self.observed_at.isoformat(),
        }


__all__ = ['ProviderChangeType', 'ProviderChangeSource', 'ProviderChange']