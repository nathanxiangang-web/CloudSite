from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class SnapshotEntry:
    resource_id: str
    path: str
    name: str
    size: int | None = None
    modified_at: datetime | None = None
    content_hash: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CategorySnapshot:
    category_id: str
    provider_id: str
    entries: list[SnapshotEntry]
    pagination_complete: bool
    taken_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def entry_ids(self) -> set[str]:
        return {e.resource_id for e in self.entries}

    @property
    def is_partial(self) -> bool:
        return not self.pagination_complete


__all__ = ['SnapshotEntry', 'CategorySnapshot']