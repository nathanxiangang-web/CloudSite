from __future__ import annotations

from cloudsite.modules.indexing.application.known_change_recorder import KnownChangeRecorder
from cloudsite.modules.indexing.domain.provider_change import ProviderChangeSource, ProviderChangeType

_REC = KnownChangeRecorder()

def test_record_create():
    pc = _REC.record_create(root_mapping_id=1, path="/a/b.txt")
    assert pc.change_type is ProviderChangeType.CREATE
    assert pc.source is ProviderChangeSource.CLOUDSITE
    assert pc.is_cloudsite_known is True

def test_record_update():
    pc = _REC.record_update(root_mapping_id=1, path="/a/b.txt")
    assert pc.change_type is ProviderChangeType.UPDATE
    assert pc.source is ProviderChangeSource.CLOUDSITE

def test_record_delete():
    pc = _REC.record_delete(root_mapping_id=1, path="/a/b.txt")
    assert pc.change_type is ProviderChangeType.DELETE
    assert pc.is_deletion is True

def test_record_rename():
    pc = _REC.record_rename(root_mapping_id=1, old_path="/a/b.txt", new_path="/a/c.txt")
    assert pc.change_type is ProviderChangeType.RENAME
    assert pc.path == "/a/c.txt"
    assert pc.old_path == "/a/b.txt"
    assert pc.is_rename_or_move is True

def test_record_move():
    pc = _REC.record_move(root_mapping_id=1, old_path="/a/b.txt", new_path="/x/b.txt")
    assert pc.change_type is ProviderChangeType.MOVE
    assert pc.path == "/x/b.txt"
    assert pc.old_path == "/a/b.txt"

def test_record_directory_dirty():
    pc = _REC.record_directory_dirty(root_mapping_id=1, path="/a/b")
    assert pc.change_type is ProviderChangeType.DIRECTORY_DIRTY
    assert pc.is_dir is True
    assert pc.requires_targeted_scan is True

def test_all_changes_are_cloudsite_source():
    for pc in [
        _REC.record_create(1, "/a"),
        _REC.record_update(1, "/a"),
        _REC.record_delete(1, "/a"),
        _REC.record_rename(1, "/a", "/b"),
        _REC.record_move(1, "/a", "/b"),
        _REC.record_directory_dirty(1, "/a"),
    ]:
        assert pc.source is ProviderChangeSource.CLOUDSITE

def test_with_optional_fields():
    pc = _REC.record_create(root_mapping_id=42, path="/a/b.txt", provider_object_id="obj-1", resource_id="res-1")
    assert pc.provider_object_id == "obj-1"
    assert pc.resource_id == "res-1"
    assert pc.root_mapping_id == 42

def test_rename_with_is_dir():
    pc = _REC.record_rename(root_mapping_id=1, old_path="/a/old", new_path="/a/new", is_dir=True)
    assert pc.is_dir is True
