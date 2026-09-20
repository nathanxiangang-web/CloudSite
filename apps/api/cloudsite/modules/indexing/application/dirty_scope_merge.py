"""R6 PR02: dirty scope merge rules (V2 doc section 30).

When a parent directory is already a dirty scope, child directories
(`/A/B`, `/A/B/C`) do not need to be added again. When enough sibling
directories under the same parent become dirty (>= threshold), the
group can be promoted to the parent directory instead.

This module is intentionally pure: it operates on dataclass records
and has no database dependency so it can be unit tested in isolation.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field


__all__ = [
    "DirtyScopeRecord",
    "PromotionCandidate",
    "MergeResult",
    "DirtyScopeMerger",
]


@dataclass(slots=True, frozen=True)
class DirtyScopeRecord:
    """A recorded dirty scope identified by root_id + path."""

    root_id: int
    path: str


@dataclass(slots=True, frozen=True)
class PromotionCandidate:
    """Suggestion to promote a group of sibling dirty scopes up to parent."""

    root_id: int
    parent_path: str
    children: tuple[str, ...]


@dataclass(slots=True)
class MergeResult:
    """Outcome of merging new dirty scopes into an existing set."""

    new_scopes: list[DirtyScopeRecord] = field(default_factory=list)
    skipped: list[DirtyScopeRecord] = field(default_factory=list)
    promotions: list[PromotionCandidate] = field(default_factory=list)


def _normalize(path: str) -> str:
    """Normalize a scope path to a canonical absolute form."""
    if not path:
        return "/"
    if not path.startswith("/"):
        path = "/" + path
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return path


def _parent_of(path: str) -> str:
    """Return the parent directory of a normalized path."""
    path = _normalize(path)
    if path == "/":
        return "/"
    idx = path.rfind("/")
    if idx <= 0:
        return "/"
    return path[:idx]


def _is_descendant(child: str, ancestor: str) -> bool:
    """Return True when `child` is a strict descendant of `ancestor`."""
    child = _normalize(child)
    ancestor = _normalize(ancestor)
    if child == ancestor:
        return False
    if ancestor == "/":
        return child != "/"
    return child.startswith(ancestor + "/")


class DirtyScopeMerger:
    """Merge and promote dirty scope rules (V2 doc section 30)."""

    def should_skip_child(self, parent_path: str, child_path: str) -> bool:
        """If `parent_path` is already a dirty scope, `child_path` need not be added."""
        return _is_descendant(child_path, parent_path)

    def find_promotion_candidates(
        self,
        dirty_scopes: list[DirtyScopeRecord],
        threshold: int = 10,
    ) -> list[PromotionCandidate]:
        """Find sibling groups eligible for promotion to their parent.

        When the same parent directory has >= `threshold` sibling dirty
        scopes, a promotion candidate is emitted for the parent. If the
        parent is itself already a dirty scope the candidate is skipped,
        since promoting to an already-dirty parent would be redundant.
        """
        if threshold <= 0:
            return []

        already_dirty: set[tuple[int, str]] = set()
        groups: dict[tuple[int, str], list[str]] = defaultdict(list)
        for scope in dirty_scopes:
            norm = _normalize(scope.path)
            already_dirty.add((scope.root_id, norm))
            if norm == "/":
                continue
            parent = _parent_of(norm)
            groups[(scope.root_id, parent)].append(norm)

        candidates: list[PromotionCandidate] = []
        for (root_id, parent_path), children in groups.items():
            unique_children = tuple(sorted(set(children)))
            if len(unique_children) < threshold:
                continue
            if (root_id, parent_path) in already_dirty:
                continue
            candidates.append(
                PromotionCandidate(
                    root_id=root_id,
                    parent_path=parent_path,
                    children=unique_children,
                )
            )
        candidates.sort(key=lambda c: (c.root_id, c.parent_path))
        return candidates

    def merge(
        self,
        existing: list[DirtyScopeRecord],
        new_scopes: list[tuple[int, str]],
    ) -> MergeResult:
        """Merge `new_scopes` into `existing`.

        - A new scope whose path is a strict descendant of an already-dirty
          scope (in `existing` or added earlier in this same merge) is skipped.
        - Promotions are computed over the merged set (existing + added).
        """
        existing_normalized: list[DirtyScopeRecord] = [
            DirtyScopeRecord(root_id=r.root_id, path=_normalize(r.path))
            for r in existing
        ]

        added: list[DirtyScopeRecord] = []
        skipped: list[DirtyScopeRecord] = []
        for root_id, path in new_scopes:
            norm = _normalize(path)
            record = DirtyScopeRecord(root_id=root_id, path=norm)
            if any(
                e.root_id == root_id and _is_descendant(norm, e.path)
                for e in existing_normalized
            ):
                skipped.append(record)
                continue
            if any(
                a.root_id == root_id and _is_descendant(norm, a.path)
                for a in added
            ):
                skipped.append(record)
                continue
            added.append(record)

        merged_set: list[DirtyScopeRecord] = list(existing_normalized) + added
        promotions = self.find_promotion_candidates(merged_set)
        return MergeResult(
            new_scopes=added,
            skipped=skipped,
            promotions=promotions,
        )
