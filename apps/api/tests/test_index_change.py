"""R7 PR01: IndexChange domain model tests (V2 doc section 37)."""

from __future__ import annotations

from datetime import datetime, timezone

from cloudsite.modules.indexing.domain.index_change import (
    IndexChange,
    IndexChangeType,
    SearchAction,
)


def test_change_type_values():
    assert IndexChangeType.RESOURCE_ADDED.value == 'resource_added'
    assert IndexChangeType.RESOURCE_UPDATED.value == 'resource_updated'
    assert IndexChangeType.RESOURCE_RENAMED.value == 'resource_renamed'
    assert IndexChangeType.RESOURCE_MOVED.value == 'resource_moved'
    assert IndexChangeType.RESOURCE_REMOVED.value == 'resource_removed'


def test_search_action_values():
    assert SearchAction.INSERT.value == 'INSERT'
    assert SearchAction.UPDATE.value == 'UPDATE'
    assert SearchAction.DELETE.value == 'DELETE'


def test_added_maps_to_insert():
    ic = IndexChange(
        change_type=IndexChangeType.RESOURCE_ADDED,
        resource_id='r1',
        root_mapping_id=1,
        path='/a/b.txt',
        name='b.txt',
    )
    assert ic.search_action is SearchAction.INSERT


def test_updated_maps_to_update():
    ic = IndexChange(
        change_type=IndexChangeType.RESOURCE_UPDATED,
        resource_id='r1',
        root_mapping_id=1,
        path='/a/b.txt',
        name='b.txt',
    )
    assert ic.search_action is SearchAction.UPDATE


def test_renamed_maps_to_update():
    ic = IndexChange(
        change_type=IndexChangeType.RESOURCE_RENAMED,
        resource_id='r1',
        root_mapping_id=1,
        path='/a/c.txt',
        name='c.txt',
        old_path='/a/b.txt',
    )
    assert ic.search_action is SearchAction.UPDATE


def test_moved_maps_to_update():
    ic = IndexChange(
        change_type=IndexChangeType.RESOURCE_MOVED,
        resource_id='r1',
        root_mapping_id=1,
        path='/x/b.txt',
        name='b.txt',
        old_path='/a/b.txt',
    )
    assert ic.search_action is SearchAction.UPDATE


def test_removed_maps_to_delete():
    ic = IndexChange(
        change_type=IndexChangeType.RESOURCE_REMOVED,
        resource_id='r1',
        root_mapping_id=1,
        path='/a/b.txt',
        name='b.txt',
    )
    assert ic.search_action is SearchAction.DELETE


def test_is_write():
    added = IndexChange(
        change_type=IndexChangeType.RESOURCE_ADDED,
        resource_id='r1',
        root_mapping_id=1,
        path='/a/b.txt',
        name='b.txt',
    )
    assert added.is_write is True

    removed = IndexChange(
        change_type=IndexChangeType.RESOURCE_REMOVED,
        resource_id='r1',
        root_mapping_id=1,
        path='/a/b.txt',
        name='b.txt',
    )
    assert removed.is_write is False


def test_is_removal():
    removed = IndexChange(
        change_type=IndexChangeType.RESOURCE_REMOVED,
        resource_id='r1',
        root_mapping_id=1,
        path='/a/b.txt',
        name='b.txt',
    )
    assert removed.is_removal is True

    added = IndexChange(
        change_type=IndexChangeType.RESOURCE_ADDED,
        resource_id='r1',
        root_mapping_id=1,
        path='/a/b.txt',
        name='b.txt',
    )
    assert added.is_removal is False


def test_is_path_change():
    renamed = IndexChange(
        change_type=IndexChangeType.RESOURCE_RENAMED,
        resource_id='r1',
        root_mapping_id=1,
        path='/a/c.txt',
        name='c.txt',
        old_path='/a/b.txt',
    )
    assert renamed.is_path_change is True

    moved = IndexChange(
        change_type=IndexChangeType.RESOURCE_MOVED,
        resource_id='r1',
        root_mapping_id=1,
        path='/x/b.txt',
        name='b.txt',
        old_path='/a/b.txt',
    )
    assert moved.is_path_change is True

    added = IndexChange(
        change_type=IndexChangeType.RESOURCE_ADDED,
        resource_id='r1',
        root_mapping_id=1,
        path='/a/b.txt',
        name='b.txt',
    )
    assert added.is_path_change is False


def test_default_optional_fields():
    ic = IndexChange(
        change_type=IndexChangeType.RESOURCE_ADDED,
        resource_id='r1',
        root_mapping_id=1,
        path='/a/b.txt',
        name='b.txt',
    )
    assert ic.is_dir is False
    assert ic.folder_id is None
    assert ic.old_path is None
    assert ic.metadata is None


def test_default_timestamp_is_utc_now():
    before = datetime.now(timezone.utc)
    ic = IndexChange(
        change_type=IndexChangeType.RESOURCE_ADDED,
        resource_id='r1',
        root_mapping_id=1,
        path='/a/b.txt',
        name='b.txt',
    )
    after = datetime.now(timezone.utc)
    assert before <= ic.timestamp <= after
    assert ic.timestamp.tzinfo is not None


def test_to_dict():
    ic = IndexChange(
        change_type=IndexChangeType.RESOURCE_MOVED,
        resource_id='r1',
        root_mapping_id=42,
        path='/x/b.txt',
        name='b.txt',
        is_dir=False,
        folder_id='f1',
        old_path='/a/b.txt',
    )
    d = ic.to_dict()
    assert d['change_type'] == 'resource_moved'
    assert d['resource_id'] == 'r1'
    assert d['root_mapping_id'] == 42
    assert d['path'] == '/x/b.txt'
    assert d['name'] == 'b.txt'
    assert d['is_dir'] is False
    assert d['folder_id'] == 'f1'
    assert d['old_path'] == '/a/b.txt'
    assert d['search_action'] == 'UPDATE'
    assert 'timestamp' in d


def test_folder_index_change():
    ic = IndexChange(
        change_type=IndexChangeType.RESOURCE_ADDED,
        resource_id='folder-1',
        root_mapping_id=1,
        path='/software',
        name='software',
        is_dir=True,
        folder_id='folder-1',
    )
    assert ic.is_dir is True
    assert ic.folder_id == 'folder-1'
    assert ic.search_action is SearchAction.INSERT