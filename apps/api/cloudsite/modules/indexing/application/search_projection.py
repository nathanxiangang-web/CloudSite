from __future__ import annotations

from dataclasses import dataclass, field

from ..domain.index_change import IndexChange, SearchAction


@dataclass(slots=True)
class SearchProjectionBatch:
    """Grouped search operations derived from a list of IndexChange events."""

    inserts: list[IndexChange] = field(default_factory=list)
    updates: list[IndexChange] = field(default_factory=list)
    deletes: list[IndexChange] = field(default_factory=list)
    by_root: dict[int, list[IndexChange]] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return len(self.inserts) + len(self.updates) + len(self.deletes)

    @property
    def is_empty(self) -> bool:
        return self.total == 0

    def to_summary(self) -> dict[str, int]:
        return {
            "inserts": len(self.inserts),
            "updates": len(self.updates),
            "deletes": len(self.deletes),
            "total": self.total,
        }


class SearchProjectionMapper:
    """Map IndexChange events to grouped search operations (V2 §37)."""

    def map(self, changes: list[IndexChange]) -> SearchProjectionBatch:
        batch = SearchProjectionBatch()
        for change in changes:
            action = change.search_action
            if action is SearchAction.INSERT:
                batch.inserts.append(change)
            elif action is SearchAction.UPDATE:
                batch.updates.append(change)
            elif action is SearchAction.DELETE:
                batch.deletes.append(change)
            root = change.root_mapping_id
            batch.by_root.setdefault(root, []).append(change)
        return batch

    def map_single(self, change: IndexChange) -> SearchProjectionBatch:
        return self.map([change])


__all__ = ["SearchProjectionBatch", "SearchProjectionMapper"]