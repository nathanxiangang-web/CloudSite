from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(slots=True)
class SearchDirtyState:
    """Tracks whether the search projection for a root is dirty (V2 §39).

    When Resources commit succeeds but the search projection fails, the
    root is marked dirty.  Resources are never rolled back for search
    failures.  A replay/rebuild must restore consistency.
    """

    root_mapping_id: int
    search_dirty: bool = False
    last_error_code: str | None = None
    last_error_message: str | None = None
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    replay_attempts: int = 0

    def mark_dirty(
        self,
        error_code: str,
        error_message: str = "",
        now: datetime | None = None,
    ) -> None:
        """Mark search projection as dirty after a projection failure."""
        now = now or datetime.now(timezone.utc)
        self.search_dirty = True
        self.last_error_code = error_code
        self.last_error_message = error_message
        self.last_failure_at = now

    def mark_clean(self, now: datetime | None = None) -> None:
        """Mark search projection as clean after successful replay/rebuild."""
        now = now or datetime.now(timezone.utc)
        self.search_dirty = False
        self.last_error_code = None
        self.last_error_message = None
        self.last_success_at = now

    def increment_replay_attempt(self) -> int:
        self.replay_attempts += 1
        return self.replay_attempts

    @property
    def needs_replay(self) -> bool:
        """True when search projection must be replayed."""
        return self.search_dirty

    @property
    def has_error(self) -> bool:
        return self.last_error_code is not None


__all__ = ["SearchDirtyState"]