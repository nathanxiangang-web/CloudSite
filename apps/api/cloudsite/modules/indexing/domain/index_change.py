from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class IndexChangeType(str, Enum):
    """Reconcile output events that drive the search projection (V2 §37)."""

    RESOURCE_ADDED = 'resource_added'
    RESOURCE_UPDATED = 'resource_updated'
    RESOURCE_RENAMED = 'resource_renamed'
    RESOURCE_MOVED = 'resource_moved'
    RESOURCE_REMOVED = 'resource_removed'


class SearchAction(str, Enum):
    """Low-level search operation derived from an IndexChange."""

    INSERT = 'INSERT'
    UPDATE = 'UPDATE'
    DELETE = 'DELETE'


_SEARCH_ACTION_MAP: dict[IndexChangeType, SearchAction] = {
    IndexChangeType.RESOURCE_ADDED: SearchAction.INSERT,
    IndexChangeType.RESOURCE_UPDATED: SearchAction.UPDATE,
    IndexChangeType.RESOURCE_RENAMED: SearchAction.UPDATE,
    IndexChangeType.RESOURCE_MOVED: SearchAction.UPDATE,
    IndexChangeType.RESOURCE_REMOVED: SearchAction.DELETE,
}


@dataclass(slots=True)
class IndexChange:
    """A single authoritative index change emitted by reconcile (V2 §37).

    Consumed by the search projection layer to incrementally update FTS
    rows instead of doing a full rebuild on every cycle.
    """

    change_type: IndexChangeType
    resource_id: str
    root_mapping_id: int
    path: str
    name: str
    is_dir: bool = False
    folder_id: str | None = None
    old_path: str | None = None
    metadata: dict[str, Any] | None = None
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def search_action(self) -> SearchAction:
        """Map this change to the low-level search operation."""
        return _SEARCH_ACTION_MAP[self.change_type]

    @property
    def is_write(self) -> bool:
        """True for INSERT or UPDATE (rows that need data)."""
        return self.search_action is not SearchAction.DELETE

    @property
    def is_removal(self) -> bool:
        return self.change_type is IndexChangeType.RESOURCE_REMOVED

    @property
    def is_path_change(self) -> bool:
        """Rename or move — old_path is meaningful."""
        return self.change_type in (
            IndexChangeType.RESOURCE_RENAMED,
            IndexChangeType.RESOURCE_MOVED,
        )

    def to_dict(self) -> dict[str, str | int | bool | None]:
        return {
            'change_type': self.change_type.value,
            'resource_id': self.resource_id,
            'root_mapping_id': self.root_mapping_id,
            'path': self.path,
            'name': self.name,
            'is_dir': self.is_dir,
            'folder_id': self.folder_id,
            'old_path': self.old_path,
            'search_action': self.search_action.value,
            'timestamp': self.timestamp.isoformat(),
        }


__all__ = ['IndexChangeType', 'SearchAction', 'IndexChange']