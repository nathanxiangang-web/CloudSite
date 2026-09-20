"""R6 PR04: ProviderChange domain model tests (V2 doc section 25)."""

from __future__ import annotations

from datetime import datetime, timezone

from cloudsite.modules.indexing.domain.provider_change import (
    ProviderChange,
    ProviderChangeSource,
    ProviderChangeType,
)


def test_change_type_values():
    assert ProviderChangeType.CREATE.value == 'create'
    assert ProviderChangeType.UPDATE.value == 'update'
    assert ProviderChangeType.DELETE.value == 'delete'
    assert ProviderChangeType.RENAME.value == 'rename'
    assert ProviderChangeType.MOVE.value == 'move'
    assert ProviderChangeType.DIRECTORY_DIRTY.value == 'directory_dirty'


def test_source_values():
    assert ProviderChangeSource.CLOUDSITE.value == 'cloudsite'
    assert ProviderChangeSource.PROVIDER_DELTA.value == 'provider_delta'
    assert ProviderChangeSource.PROVIDER_WEBHOOK.value == 'provider_webhook'
    assert ProviderChangeSource.VERIFICATION.value == 'verification'
    assert ProviderChangeSource.MANUAL.value == 'manual'


def test_default_source_is_verification():
    pc = ProviderChange(
        change_type=ProviderChangeType.CREATE,
        root_mapping_id=1,
        path='/a/b.txt',
    )
    assert pc.source is ProviderChangeSource.VERIFICATION


def test_default_observed_at_is_utc_now():
    before = datetime.now(timezone.utc)
    pc = ProviderChange(
        change_type=ProviderChangeType.CREATE,
        root_mapping_id=1,
        path='/a/b.txt',
    )
    after = datetime.now(timezone.utc)
    assert before <= pc.observed_at <= after
    assert pc.observed_at.tzinfo is not None


def test_default_optional_fields_are_none():
    pc = ProviderChange(
        change_type=ProviderChangeType.CREATE,
        root_mapping_id=1,
        path='/a/b.txt',
    )
    assert pc.provider_object_id is None
    assert pc.resource_id is None
    assert pc.old_path is None
    assert pc.is_dir is False


def test_is_deletion():
    pc = ProviderChange(
        change_type=ProviderChangeType.DELETE,
        root_mapping_id=1,
        path='/a/b.txt',
    )
    assert pc.is_deletion is True

    pc2 = ProviderChange(
        change_type=ProviderChangeType.CREATE,
        root_mapping_id=1,
        path='/a/b.txt',
    )
    assert pc2.is_deletion is False


def test_is_rename_or_move():
    rename = ProviderChange(
        change_type=ProviderChangeType.RENAME,
        root_mapping_id=1,
        path='/a/c.txt',
        old_path='/a/b.txt',
    )
    assert rename.is_rename_or_move is True

    move = ProviderChange(
        change_type=ProviderChangeType.MOVE,
        root_mapping_id=1,
        path='/x/c.txt',
        old_path='/a/b.txt',
    )
    assert move.is_rename_or_move is True

    create = ProviderChange(
        change_type=ProviderChangeType.CREATE,
        root_mapping_id=1,
        path='/a/b.txt',
    )
    assert create.is_rename_or_move is False


def test_is_directory_dirty():
    pc = ProviderChange(
        change_type=ProviderChangeType.DIRECTORY_DIRTY,
        root_mapping_id=1,
        path='/a/b',
        is_dir=True,
    )
    assert pc.is_directory_dirty is True

    pc2 = ProviderChange(
        change_type=ProviderChangeType.UPDATE,
        root_mapping_id=1,
        path='/a/b.txt',
    )
    assert pc2.is_directory_dirty is False


def test_requires_targeted_scan():
    dirty = ProviderChange(
        change_type=ProviderChangeType.DIRECTORY_DIRTY,
        root_mapping_id=1,
        path='/a/b',
        is_dir=True,
    )
    assert dirty.requires_targeted_scan is True

    create = ProviderChange(
        change_type=ProviderChangeType.CREATE,
        root_mapping_id=1,
        path='/a/b.txt',
    )
    assert create.requires_targeted_scan is False


def test_is_cloudsite_known():
    pc = ProviderChange(
        change_type=ProviderChangeType.RENAME,
        root_mapping_id=1,
        path='/a/c.txt',
        old_path='/a/b.txt',
        source=ProviderChangeSource.CLOUDSITE,
    )
    assert pc.is_cloudsite_known is True

    pc2 = ProviderChange(
        change_type=ProviderChangeType.CREATE,
        root_mapping_id=1,
        path='/a/b.txt',
        source=ProviderChangeSource.VERIFICATION,
    )
    assert pc2.is_cloudsite_known is False


def test_to_dict_roundtrip():
    pc = ProviderChange(
        change_type=ProviderChangeType.MOVE,
        root_mapping_id=42,
        path='/x/y.txt',
        old_path='/a/b.txt',
        is_dir=False,
        provider_object_id='obj-123',
        resource_id='res-456',
        source=ProviderChangeSource.PROVIDER_DELTA,
    )
    d = pc.to_dict()
    assert d['change_type'] == 'move'
    assert d['root_mapping_id'] == 42
    assert d['path'] == '/x/y.txt'
    assert d['old_path'] == '/a/b.txt'
    assert d['is_dir'] is False
    assert d['provider_object_id'] == 'obj-123'
    assert d['resource_id'] == 'res-456'
    assert d['source'] == 'provider_delta'
    assert 'observed_at' in d
    assert isinstance(d['observed_at'], str)


def test_full_change_with_all_fields():
    pc = ProviderChange(
        change_type=ProviderChangeType.DIRECTORY_DIRTY,
        root_mapping_id=7,
        path='/software',
        is_dir=True,
        provider_object_id='dir-001',
        resource_id='folder-001',
        source=ProviderChangeSource.VERIFICATION,
    )
    assert pc.change_type is ProviderChangeType.DIRECTORY_DIRTY
    assert pc.root_mapping_id == 7
    assert pc.path == '/software'
    assert pc.is_dir is True
    assert pc.provider_object_id == 'dir-001'
    assert pc.resource_id == 'folder-001'
    assert pc.source is ProviderChangeSource.VERIFICATION
    assert pc.is_directory_dirty is True
    assert pc.requires_targeted_scan is True
    assert pc.is_deletion is False
    assert pc.is_rename_or_move is False