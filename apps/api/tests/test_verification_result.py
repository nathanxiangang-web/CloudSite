"""R8 PR02: Verification Result tests (V2 doc section 32)."""

from __future__ import annotations

from datetime import datetime, timezone

from cloudsite.modules.indexing.domain.verification_result import (
    VerificationBatchResult,
    VerificationResult,
)

_NOW = datetime(2026, 9, 21, 1, 0, 0, tzinfo=timezone.utc)


def _result(match=True, path="/a", root=1) -> VerificationResult:
    return VerificationResult(
        root_mapping_id=root,
        path=path,
        fingerprint_match=match,
        checked_at=_NOW,
    )


def test_verified_when_match():
    r = _result(match=True)
    assert r.is_verified is True
    assert r.is_dirty is False


def test_dirty_when_mismatch():
    r = _result(match=False)
    assert r.is_verified is False
    assert r.is_dirty is True


def test_default_is_verified():
    r = VerificationResult(root_mapping_id=1, path="/a")
    assert r.is_verified is True
    assert r.is_dirty is False


def test_has_previous_fingerprint():
    r = VerificationResult(root_mapping_id=1, path="/a", previous_fingerprint="abc")
    assert r.has_previous_fingerprint is True

    r2 = VerificationResult(root_mapping_id=1, path="/a")
    assert r2.has_previous_fingerprint is False


def test_to_dict():
    r = VerificationResult(
        root_mapping_id=42,
        path="/x",
        fingerprint_match=False,
        child_count=5,
        checked_at=_NOW,
    )
    d = r.to_dict()
    assert d["root_mapping_id"] == 42
    assert d["path"] == "/x"
    assert d["fingerprint_match"] is False
    assert d["is_verified"] is False
    assert d["is_dirty"] is True
    assert d["child_count"] == 5


def test_batch_verified_and_dirty_counts():
    batch = VerificationBatchResult()
    batch.add(_result(match=True, path="/a"))
    batch.add(_result(match=True, path="/b"))
    batch.add(_result(match=False, path="/c"))
    batch.add(_result(match=False, path="/d"))
    assert batch.verified_count == 2
    assert batch.dirty_count == 2
    assert batch.total == 4


def test_batch_dirty_paths():
    batch = VerificationBatchResult()
    batch.add(_result(match=True, path="/a"))
    batch.add(_result(match=False, path="/b"))
    batch.add(_result(match=False, path="/c"))
    assert batch.dirty_paths == ["/b", "/c"]


def test_batch_empty():
    batch = VerificationBatchResult()
    assert batch.total == 0
    assert batch.verified_count == 0
    assert batch.dirty_count == 0
    assert batch.dirty_paths == []


def test_batch_to_summary():
    batch = VerificationBatchResult()
    batch.add(_result(match=True, path="/a"))
    batch.add(_result(match=False, path="/b"))
    s = batch.to_summary()
    assert s["total"] == 2
    assert s["verified"] == 1
    assert s["dirty"] == 1
    assert s["dirty_paths"] == ["/b"]


def test_default_checked_at_is_utc_now():
    before = datetime.now(timezone.utc)
    r = VerificationResult(root_mapping_id=1, path="/a")
    after = datetime.now(timezone.utc)
    assert before <= r.checked_at <= after
    assert r.checked_at.tzinfo is not None


def test_multi_root_isolation():
    batch = VerificationBatchResult()
    batch.add(_result(match=False, path="/a", root=1))
    batch.add(_result(match=False, path="/a", root=2))
    assert batch.dirty_count == 2
    assert all(r.root_mapping_id in (1, 2) for r in batch.results)