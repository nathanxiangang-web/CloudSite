from __future__ import annotations

from cloudsite.modules.indexing.application.audit_repair_executor import AuditRepairExecutor
from cloudsite.modules.indexing.domain.audit_diff import AuditDiffEntry, AuditDiffResult, AuditDiffType


def _entry(dt, path="/a"):
    return AuditDiffEntry(diff_type=dt, root_mapping_id=1, path=path)

def _result(entries, completed=True):
    r = AuditDiffResult(root_mapping_id=1, audit_completed=completed)
    for e in entries:
        r.add(e)
    return r


def test_repair_all_success():
    ex = AuditRepairExecutor()
    r = ex.execute(_result([_entry(AuditDiffType.CHANGED), _entry(AuditDiffType.MISSING_IN_PROVIDER)]), lambda e: True)
    assert r.total_repaired == 2
    assert r.total_failed == 0
    assert r.success is True


def test_repair_partial_failure():
    ex = AuditRepairExecutor()
    r = ex.execute(_result([_entry(AuditDiffType.CHANGED, "/a"), _entry(AuditDiffType.CHANGED, "/b")]), lambda e: e.path == "/a")
    assert r.total_repaired == 1
    assert r.total_failed == 1
    assert r.success is False


def test_identity_conflict_skipped():
    ex = AuditRepairExecutor()
    r = ex.execute(_result([_entry(AuditDiffType.CHANGED), _entry(AuditDiffType.IDENTITY_CONFLICT)]), lambda e: True)
    assert r.total_repaired == 1
    assert len(r.skipped) == 1
    assert r.skipped[0].diff_type is AuditDiffType.IDENTITY_CONFLICT


def test_audit_not_completed_skips_all():
    ex = AuditRepairExecutor()
    r = ex.execute(_result([_entry(AuditDiffType.CHANGED)], completed=False), lambda e: True)
    assert r.total_repaired == 0
    assert len(r.skipped) == 1


def test_clean_audit_no_repair():
    ex = AuditRepairExecutor()
    r = ex.execute(_result([]), lambda e: True)
    assert r.total_repaired == 0
    assert r.success is False


def test_all_identity_conflict_skipped():
    ex = AuditRepairExecutor()
    r = ex.execute(_result([_entry(AuditDiffType.IDENTITY_CONFLICT)]), lambda e: True)
    assert r.total_repaired == 0
    assert len(r.skipped) == 1
