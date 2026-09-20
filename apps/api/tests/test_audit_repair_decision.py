from __future__ import annotations

from cloudsite.modules.indexing.application.audit_repair_decision import AuditRepairDecider
from cloudsite.modules.indexing.domain.audit_diff import AuditDiffEntry, AuditDiffResult, AuditDiffType


def _entry(dt, root=1):
    return AuditDiffEntry(diff_type=dt, root_mapping_id=root, path="/a/b.txt")

def _result(entries=None, completed=True, root=1):
    r = AuditDiffResult(root_mapping_id=root, audit_completed=completed)
    for e in (entries or []):
        r.add(e)
    return r

def test_audit_not_completed():
    d = AuditRepairDecider().decide(_result(completed=False))
    assert d.can_auto_repair is False and d.reason == "audit_not_completed"

def test_clean_no_repair():
    d = AuditRepairDecider().decide(_result(entries=[]))
    assert d.can_auto_repair is False and d.reason == "no_discrepancies"

def test_auto_repairable():
    d = AuditRepairDecider().decide(_result([_entry(AuditDiffType.CHANGED), _entry(AuditDiffType.MISSING_IN_PROVIDER)]))
    assert d.can_auto_repair is True and d.should_repair is True and d.repairable_entries == 2

def test_identity_conflict_manual():
    d = AuditRepairDecider().decide(_result([_entry(AuditDiffType.IDENTITY_CONFLICT)]))
    assert d.can_auto_repair is False and d.requires_manual_intervention is True and d.manual_entries == 1

def test_mixed():
    d = AuditRepairDecider().decide(_result([_entry(AuditDiffType.CHANGED), _entry(AuditDiffType.IDENTITY_CONFLICT)]))
    assert d.can_auto_repair is True and d.repairable_entries == 1 and d.manual_entries == 1 and d.reason == "partial"

def test_duplicate_identity_auto():
    d = AuditRepairDecider().decide(_result([_entry(AuditDiffType.DUPLICATE_IDENTITY)]))
    assert d.can_auto_repair is True and d.should_repair is True

def test_unexpected_path_auto():
    d = AuditRepairDecider().decide(_result([_entry(AuditDiffType.UNEXPECTED_PATH)]))
    assert d.can_auto_repair is True and d.should_repair is True
