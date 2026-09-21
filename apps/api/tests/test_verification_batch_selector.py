"""R8 PR01: Verification Batch Selector tests (V2 doc sections 32-33)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from cloudsite.modules.indexing.application.verification_batch_selector import (
    VerificationBatchSelector,
    VerificationCandidate,
    VerificationPriority,
)


_NOW = datetime(2026, 9, 21, 0, 0, 0, tzinfo=timezone.utc)


def _candidate(
    path: str = '/a',
    depth: int = 0,
    last_verified_at: datetime | None = None,
    last_changed_at: datetime | None = None,
    is_high_risk: bool = False,
    previously_failed: bool = False,
    root_mapping_id: int = 1,
) -> VerificationCandidate:
    return VerificationCandidate(
        root_mapping_id=root_mapping_id,
        path=path,
        depth=depth,
        last_verified_at=last_verified_at,
        last_changed_at=last_changed_at,
        is_high_risk=is_high_risk,
        previously_failed=previously_failed,
    )


def test_previously_failed_highest_priority():
    c = _candidate(previously_failed=True)
    assert c.compute_priority(_NOW) == VerificationPriority.PREVIOUSLY_FAILED


def test_long_unverified_outranks_high_risk_for_coverage():
    c = _candidate(
        path="/a/b",
        depth=2,
        last_verified_at=_NOW - timedelta(days=60),
        is_high_risk=True,
    )
    assert c.compute_priority(_NOW) == VerificationPriority.LONG_UNVERIFIED


def test_high_risk_priority_after_coverage_guard():
    c = _candidate(
        is_high_risk=True,
        last_verified_at=_NOW - timedelta(days=10),
    )
    assert c.compute_priority(_NOW) == VerificationPriority.HIGH_RISK


def test_top_level_priority():
    verified = _NOW - timedelta(days=10)
    c = _candidate(path='/software', depth=0, last_verified_at=verified)
    assert c.compute_priority(_NOW) == VerificationPriority.TOP_LEVEL

    c2 = _candidate(
        path='/software/sub',
        depth=1,
        last_verified_at=verified,
    )
    assert c2.compute_priority(_NOW) == VerificationPriority.TOP_LEVEL


def test_recently_changed_priority():
    changed = _NOW - timedelta(hours=12)
    c = _candidate(path='/a/b', depth=2, last_changed_at=changed)
    assert c.compute_priority(_NOW) == VerificationPriority.RECENTLY_CHANGED


def test_recently_active_priority():
    verified = _NOW - timedelta(days=3)
    c = _candidate(path='/a/b', depth=2, last_verified_at=verified)
    assert c.compute_priority(_NOW) == VerificationPriority.RECENTLY_ACTIVE


def test_long_unverified_priority():
    old = _NOW - timedelta(days=60)
    c = _candidate(path='/a/b', depth=2, last_verified_at=old)
    assert c.compute_priority(_NOW) == VerificationPriority.LONG_UNVERIFIED


def test_never_verified_is_long_unverified():
    c = _candidate(path='/a/b', depth=2, last_verified_at=None)
    assert c.compute_priority(_NOW) == VerificationPriority.LONG_UNVERIFIED


def test_normal_priority():
    verified = _NOW - timedelta(days=10)
    c = _candidate(path='/a/b', depth=2, last_verified_at=verified)
    assert c.compute_priority(_NOW) == VerificationPriority.NORMAL


def test_select_returns_batch_size():
    selector = VerificationBatchSelector(batch_size=3)
    candidates = [_candidate(path=f'/d{i}', depth=2) for i in range(10)]
    result = selector.select(candidates, now=_NOW)
    assert len(result) == 3


def test_select_orders_by_priority():
    selector = VerificationBatchSelector(batch_size=10)
    failed = _candidate(path='/failed', depth=2, previously_failed=True)
    never = _candidate(path='/never', depth=2)
    normal = _candidate(
        path='/normal',
        depth=2,
        last_verified_at=_NOW - timedelta(days=10),
    )
    top = _candidate(
        path='/top',
        depth=0,
        last_verified_at=_NOW - timedelta(days=10),
    )
    result = selector.select([normal, failed, top, never], now=_NOW)
    assert [item.path for item in result] == [
        '/failed',
        '/never',
        '/top',
        '/normal',
    ]


def test_select_empty_candidates():
    selector = VerificationBatchSelector()
    assert selector.select([], now=_NOW) == []


def test_select_fewer_than_batch_size():
    selector = VerificationBatchSelector(batch_size=10)
    candidates = [_candidate(path='/a'), _candidate(path='/b')]
    result = selector.select(candidates, now=_NOW)
    assert len(result) == 2


def test_batch_size_must_be_positive():
    try:
        VerificationBatchSelector(batch_size=0)
        assert False, "Should have raised"
    except ValueError:
        pass


def test_select_is_deterministic():
    selector = VerificationBatchSelector(batch_size=5)
    candidates = [_candidate(path=f'/d{i:02d}', depth=2) for i in range(20)]
    r1 = selector.select(list(candidates), now=_NOW)
    r2 = selector.select(list(candidates), now=_NOW)
    assert [c.path for c in r1] == [c.path for c in r2]


def test_tie_break_by_path():
    selector = VerificationBatchSelector(batch_size=5)
    c1 = _candidate(path='/z', depth=0)
    c2 = _candidate(path='/a', depth=0)
    c3 = _candidate(path='/m', depth=0)
    result = selector.select([c1, c2, c3], now=_NOW)
    assert [c.path for c in result] == ['/a', '/m', '/z']


def test_multi_root_isolation():
    selector = VerificationBatchSelector(batch_size=10)
    c1 = _candidate(path='/a', depth=0, root_mapping_id=1)
    c2 = _candidate(path='/a', depth=0, root_mapping_id=2)
    result = selector.select([c1, c2], now=_NOW)
    assert len(result) == 2
    assert {c.root_mapping_id for c in result} == {1, 2}

def test_never_verified_deep_path_cannot_starve_behind_top_level():
    selector = VerificationBatchSelector(batch_size=1)
    top = _candidate(
        path="/top",
        depth=0,
        last_verified_at=_NOW - timedelta(hours=1),
    )
    deep_never = _candidate(path="/top/a/b/c", depth=4, last_verified_at=None)

    result = selector.select([top, deep_never], now=_NOW)

    assert [item.path for item in result] == ["/top/a/b/c"]


def test_same_priority_rotates_oldest_verified_first():
    selector = VerificationBatchSelector(batch_size=1)
    older = _candidate(
        path="/a",
        depth=0,
        last_verified_at=_NOW - timedelta(days=20),
    )
    newer = _candidate(
        path="/b",
        depth=0,
        last_verified_at=_NOW - timedelta(days=10),
    )

    first = selector.select([newer, older], now=_NOW)
    assert [item.path for item in first] == ["/a"]

    older.last_verified_at = _NOW
    second = selector.select([newer, older], now=_NOW)
    assert [item.path for item in second] == ["/b"]
