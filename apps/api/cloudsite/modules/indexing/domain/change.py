from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ChangeType(str, Enum):
    ADDED = 'added'
    CHANGED = 'changed'
    RENAMED = 'renamed'
    MOVED = 'moved'
    REMOVED = 'removed'
    UNCHANGED = 'unchanged'
    CONFLICT = 'conflict'


@dataclass(slots=True)
class ChangeRecord:
    change_type: ChangeType
    resource_id: str
    category_id: str
    provider_id: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_removal(self) -> bool:
        return self.change_type is ChangeType.REMOVED

    @property
    def is_write(self) -> bool:
        return self.change_type not in (ChangeType.UNCHANGED, ChangeType.CONFLICT)


__all__ = ['ChangeType', 'ChangeRecord']