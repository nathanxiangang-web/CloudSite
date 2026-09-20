"""R9 PR01: Audit Diff model tests (V2 doc section 36)."""

from __future__ import annotations

from cloudsite.modules.indexing.domain.audit_diff import (
    AuditDiffEntry,
    AuditDiffResult,
    AuditDiffType,
)


def _entry(dt: AuditDiffType, root: int = 1, path: str = "/a/b.txt") -> AuditDiffEntry:
    return AuditDiffEntry(diff_type=dt, root_mapping_id=root, path=path)


def test_diff_type_values():
    assert AuditDiffType.MISSING_IN_PROVIDER.value == 'missing_in_provider'
    assert AuditDiffType.MISSING_IN_INDEX.value == 'missing_in_index'
    assert AuditDiffType.CHANGED.value == 'changed'
    assert AuditDiffType.IDENTITY_CONFLICT.value == 'identity_conflict'
    assert AuditDiffType.UNEXPECTED_PATH.value == 'unexpected_path'
    assert AuditDiffType.DUPLICATE_IDENTITY.value == 'duplicate_identity'


def test_is_missing_in_provider():
    e = _entry(AuditDiffType.MISSING_IN_PROVIDER)
    assert e.is_missing_in_provider is True
    assert e.is_missing_in_index is False


def test_is_missing_in_index():
    e = _entry(AuditDiffType.MISSING_IN_INDEX)
    assert e.is_missing_in_index is True
    assert e.is_missing_in_provider is False


def test_is_identity_conflict():
    e = _entry(AuditDiffType.IDENTITY_CONFLICT)
    assert e.is_identity_conflict is True


def test_requires_repair():
    assert _entry(AuditDiffType.MISSING_IN_PROVIDER).requires_repair is True
    assert _entry(AuditDiffType.MISSING_IN_INDEX).requires_repair is True
    assert _entry(AuditDiffType.CHANGED).requires_repair is True
    assert _entry(AuditDiffType.UNEXPECTED_PATH).requires_repair is True
    assert _entry(AuditDiffType.DUPLICATE_IDENTITY).requires_repair is True
    assert _entry(AuditDiffType.IDENTITY_CONFLICT).requires_repair is False


def test_to_dict():
    e = AuditDiffEntry(
        diff_type=AuditDiffType.CHANGED,
        root_mapping_id=42,
        path="/x/y.txt",
        is_dir=True,
        provider_object_id="obj-1",
        resource_id="res-1",
    )
    d = e.to_dict()
    assert d['diff_type'] == 'changed'
    assert d['root_mapping_id'] == 42
    assert d['path'] == '/x/y.txt'
    assert d['is_dir'] is True
    assert d['provider_object_id'] == 'obj-1'
    assert d['resource_id'] == 'res-1'
    assert 'detected_at' in d


def test_result_is_clean_when_no_entries_and_completed():
    r = AuditDiffResult(root_mapping_id=1, audit_completed=True)
    assert r.is_clean is True


def test_result_not_clean_when_entries_exist():
    r = AuditDiffResult(root_mapping_id=1, audit_completed=True)
    r.add(_entry(AuditDiffType.CHANGED))
    assert r.is_clean is False


def test_result_not_clean_when_audit_incomplete():
    r = AuditDiffResult(root_mapping_id=1, audit_completed=False)
    assert r.is_clean is False


def test_count_by_type():
    r = AuditDiffResult(root_mapping_id=1, audit_completed=True)
    r.add(_entry(AuditDiffType.MISSING_IN_PROVIDER))
    r.add(_entry(AuditDiffType.MISSING_IN_PROVIDER))
    r.add(_entry(AuditDiffType.CHANGED))
    r.add(_entry(AuditDiffType.IDENTITY_CONFLICT))
    c = r.count_by_type
    assert c[AuditDiffType.MISSING_IN_PROVIDER] == 2
    assert c[AuditDiffType.CHANGED] == 1
    assert c[AuditDiffType.IDENTITY_CONFLICT] == 1
    assert c[AuditDiffType.MISSING_IN_INDEX] == 0


def test_to_summary():
    r = AuditDiffResult(root_mapping_id=1, audit_completed=True)
    r.add(_entry(AuditDiffType.MISSING_IN_PROVIDER))
    r.add(_entry(AuditDiffType.CHANGED))
    s = r.to_summary()
    assert s['total'] == 2
    assert s['missing_in_provider'] == 1
    assert s['changed'] == 1
    assert s['audit_completed'] is True
    assert s['is_clean'] is False


def test_empty_result_summary():
    r = AuditDiffResult(root_mapping_id=1, audit_completed=True)
    s = r.to_summary()
    assert s['total'] == 0
    assert s['is_clean'] is True


def test_multi_root_isolation():
    r1 = AuditDiffResult(root_mapping_id=1, audit_completed=True)
    r2 = AuditDiffResult(root_mapping_id=2, audit_completed=True)
    r1.add(_entry(AuditDiffType.CHANGED, root=1))
    r2.add(_entry(AuditDiffType.MISSING_IN_INDEX, root=2))
    assert r1.root_mapping_id != r2.root_mapping_id
    assert r1.count_by_type[AuditDiffType.CHANGED] == 1
    assert r2.count_by_type[AuditDiffType.MISSING_IN_INDEX] == 1