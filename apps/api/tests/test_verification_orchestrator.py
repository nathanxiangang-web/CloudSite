from __future__ import annotations

from datetime import datetime, timezone

from cloudsite.modules.indexing.application.verification_orchestrator import VerificationOrchestrator
from cloudsite.modules.indexing.application.verification_batch_selector import VerificationCandidate

_NOW = datetime(2026, 9, 21, 1, 0, 0, tzinfo=timezone.utc)


def _candidate(path="/a", root=1, depth=0) -> VerificationCandidate:
    return VerificationCandidate(root_mapping_id=root, path=path, depth=depth)


def test_all_verified():
    orch = VerificationOrchestrator()
    result = orch.run(
        [_candidate("/a"), _candidate("/b")],
        lambda c: (True, 5),
        now=_NOW,
    )
    assert result.verified_count == 2
    assert result.dirty_count == 0
    assert result.dirty_paths == []


def test_all_dirty():
    orch = VerificationOrchestrator()
    result = orch.run(
        [_candidate("/a"), _candidate("/b")],
        lambda c: (False, 3),
        now=_NOW,
    )
    assert result.verified_count == 0
    assert result.dirty_count == 2
    assert result.dirty_paths == ["/a", "/b"]


def test_mixed():
    orch = VerificationOrchestrator()
    result = orch.run(
        [_candidate("/a"), _candidate("/b"), _candidate("/c")],
        lambda c: (c.path != "/b", 1),
        now=_NOW,
    )
    assert result.verified_count == 2
    assert result.dirty_count == 1
    assert result.dirty_paths == ["/b"]


def test_empty_candidates():
    orch = VerificationOrchestrator()
    result = orch.run([], lambda c: (True, 0), now=_NOW)
    assert result.total == 0


def test_batch_size_limit():
    orch = VerificationOrchestrator()
    orch.batch_selector = type(orch.batch_selector)(batch_size=3)
    result = orch.run(
        [_candidate(f"/d{i}", depth=2) for i in range(10)],
        lambda c: (False, 0),
        now=_NOW,
    )
    assert result.total == 3


def test_child_count_recorded():
    orch = VerificationOrchestrator()
    result = orch.run(
        [_candidate("/a")],
        lambda c: (True, 42),
        now=_NOW,
    )
    assert result.results[0].child_count == 42


def test_multi_root():
    orch = VerificationOrchestrator()
    result = orch.run(
        [_candidate("/a", root=1), _candidate("/a", root=2)],
        lambda c: (False, 0),
        now=_NOW,
    )
    assert result.dirty_count == 2
    roots = {r.root_mapping_id for r in result.results}
    assert roots == {1, 2}
