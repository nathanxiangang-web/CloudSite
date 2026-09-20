"""R6 PR02: dirty scope merge rules regression tests (V2 doc section 30).

Verifies that:
- A child of an already-dirty parent is skipped (including deeply nested).
- A child of a non-dirty parent is not skipped.
- Sibling groups below the threshold are not promoted.
- Sibling groups at/above the threshold are promoted to the parent.
- The default promotion threshold is 10.
- `merge` returns the correct new / skipped / promotions lists.
"""
from __future__ import annotations

import inspect

import pytest

from cloudsite.modules.indexing.application.dirty_scope_merge import (
    DirtyScopeMerger,
    DirtyScopeRecord,
    MergeResult,
    PromotionCandidate,
)


@pytest.fixture
def merger() -> DirtyScopeMerger:
    return DirtyScopeMerger()


def _siblings(parent: str, count: int, root_id: int = 1) -> list[DirtyScopeRecord]:
    return [
        DirtyScopeRecord(root_id=root_id, path=f"{parent}/child{i}")
        for i in range(count)
    ]


# ---------------------------------------------------------------------
# should_skip_child
# ---------------------------------------------------------------------

def test_should_skip_child_when_parent_dirty(merger: DirtyScopeMerger) -> None:
    # /A dirty -> /A/B is a descendant and must be skipped
    assert merger.should_skip_child("/A", "/A/B") is True


def test_should_not_skip_when_parent_not_dirty(merger: DirtyScopeMerger) -> None:
    # /X dirty has no relationship to /A/B -> must not skip
    assert merger.should_skip_child("/X", "/A/B") is False


def test_deeply_nested_skip(merger: DirtyScopeMerger) -> None:
    # /A dirty -> /A/B/C/D is still a descendant and must be skipped
    assert merger.should_skip_child("/A", "/A/B/C/D") is True


# ---------------------------------------------------------------------
# find_promotion_candidates
# ---------------------------------------------------------------------

def test_no_promotion_below_threshold(merger: DirtyScopeMerger) -> None:
    scopes = _siblings("/A", 9)
    assert merger.find_promotion_candidates(scopes) == []


def test_promotion_at_threshold(merger: DirtyScopeMerger) -> None:
    scopes = _siblings("/A", 10)
    candidates = merger.find_promotion_candidates(scopes)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.root_id == 1
    assert candidate.parent_path == "/A"
    assert len(candidate.children) == 10
    # children must all be the sibling scopes under /A
    assert all(c.startswith("/A/child") for c in candidate.children)


def test_promotion_threshold_default_10(merger: DirtyScopeMerger) -> None:
    # Structural: default value of `threshold` is 10
    sig = inspect.signature(merger.find_promotion_candidates)
    assert sig.parameters["threshold"].default == 10

    # Behavioral: 9 siblings -> no promotion, 10 siblings -> promotion,
    # both calls use the default threshold argument.
    assert merger.find_promotion_candidates(_siblings("/A", 9)) == []
    assert len(merger.find_promotion_candidates(_siblings("/A", 10))) == 1


# ---------------------------------------------------------------------
# merge
# ---------------------------------------------------------------------

def test_merge_skips_children_of_dirty_parents(merger: DirtyScopeMerger) -> None:
    existing = [DirtyScopeRecord(root_id=1, path="/A")]
    new_scopes = [(1, "/A/B")]
    result = merger.merge(existing, new_scopes)

    assert isinstance(result, MergeResult)
    assert result.new_scopes == []
    assert len(result.skipped) == 1
    assert result.skipped[0].root_id == 1
    assert result.skipped[0].path == "/A/B"


def test_merge_returns_new_scopes(merger: DirtyScopeMerger) -> None:
    existing: list[DirtyScopeRecord] = []
    new_scopes = [(1, "/X"), (2, "/Y")]
    result = merger.merge(existing, new_scopes)

    assert len(result.new_scopes) == 2
    assert {s.path for s in result.new_scopes} == {"/X", "/Y"}
    assert {s.root_id for s in result.new_scopes} == {1, 2}
    assert result.skipped == []


def test_merge_returns_skipped(merger: DirtyScopeMerger) -> None:
    existing = [DirtyScopeRecord(root_id=1, path="/A")]
    new_scopes = [(1, "/A/B"), (1, "/Z")]
    result = merger.merge(existing, new_scopes)

    # /A/B is a child of dirty /A -> skipped
    assert len(result.skipped) == 1
    assert result.skipped[0].path == "/A/B"
    # /Z is unrelated -> added
    assert len(result.new_scopes) == 1
    assert result.new_scopes[0].path == "/Z"


def test_merge_returns_promotions(merger: DirtyScopeMerger) -> None:
    existing: list[DirtyScopeRecord] = []
    # 10 sibling dirty scopes under /A -> eligible for promotion to /A
    new_scopes = [(1, f"/A/child{i}") for i in range(10)]
    result = merger.merge(existing, new_scopes)

    assert len(result.new_scopes) == 10
    assert len(result.promotions) == 1
    promotion = result.promotions[0]
    assert isinstance(promotion, PromotionCandidate)
    assert promotion.root_id == 1
    assert promotion.parent_path == "/A"
    assert len(promotion.children) == 10
