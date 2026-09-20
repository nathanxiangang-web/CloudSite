from __future__ import annotations

from datetime import datetime, timezone

from cloudsite.modules.indexing.domain.snapshot import CategorySnapshot, SnapshotEntry


def _entry(rid: str, path: str = '/x') -> SnapshotEntry:
    return SnapshotEntry(resource_id=rid, path=path, name=rid)


def test_entry_ids_collects_resource_ids():
    snap = CategorySnapshot(
        category_id='cat', provider_id='prov',
        entries=[_entry('a'), _entry('b'), _entry('c')],
        pagination_complete=True,
    )
    assert snap.entry_ids == {'a', 'b', 'c'}


def test_is_partial_true_when_pagination_incomplete():
    snap = CategorySnapshot(
        category_id='cat', provider_id='prov',
        entries=[_entry('a')], pagination_complete=False,
    )
    assert snap.is_partial is True


def test_is_partial_false_when_pagination_complete():
    snap = CategorySnapshot(
        category_id='cat', provider_id='prov',
        entries=[_entry('a')], pagination_complete=True,
    )
    assert snap.is_partial is False


def test_taken_at_defaults_to_utc_now():
    before = datetime.now(timezone.utc)
    snap = CategorySnapshot(
        category_id='cat', provider_id='prov',
        entries=[], pagination_complete=True,
    )
    after = datetime.now(timezone.utc)
    assert before <= snap.taken_at <= after
    assert snap.taken_at.tzinfo is not None


def test_empty_snapshot_has_no_entries():
    snap = CategorySnapshot(
        category_id='cat', provider_id='prov',
        entries=[], pagination_complete=True,
    )
    assert snap.entry_ids == set()
    assert len(snap.entries) == 0


def test_entries_metadata_isolated_per_instance():
    e1 = _entry('a')
    e2 = _entry('b')
    e1.metadata['k'] = 'v'
    assert 'k' not in e2.metadata


def test_snapshot_carries_category_and_provider():
    snap = CategorySnapshot(
        category_id='books', provider_id='alist-1',
        entries=[_entry('a')], pagination_complete=True,
    )
    assert snap.category_id == 'books'
    assert snap.provider_id == 'alist-1'