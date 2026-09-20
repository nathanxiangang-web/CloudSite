"""R7 PR02: Search Projection Mapper tests (V2 doc section 37)."""

from __future__ import annotations

from cloudsite.modules.indexing.application.search_projection import (
    SearchProjectionBatch,
    SearchProjectionMapper,
)
from cloudsite.modules.indexing.domain.index_change import IndexChange, IndexChangeType


def _change(ct: IndexChangeType, rid: str = "r1", root: int = 1, path: str = "/a/b.txt") -> IndexChange:
    return IndexChange(
        change_type=ct,
        resource_id=rid,
        root_mapping_id=root,
        path=path,
        name="b.txt",
    )


def test_empty_input():
    mapper = SearchProjectionMapper()
    batch = mapper.map([])
    assert batch.is_empty is True
    assert batch.total == 0


def test_inserts_routed_correctly():
    mapper = SearchProjectionMapper()
    batch = mapper.map([_change(IndexChangeType.RESOURCE_ADDED)])
    assert len(batch.inserts) == 1
    assert len(batch.updates) == 0
    assert len(batch.deletes) == 0


def test_updates_routed_correctly():
    mapper = SearchProjectionMapper()
    batch = mapper.map([
        _change(IndexChangeType.RESOURCE_UPDATED),
        _change(IndexChangeType.RESOURCE_RENAMED, path="/a/c.txt"),
        _change(IndexChangeType.RESOURCE_MOVED, path="/x/b.txt"),
    ])
    assert len(batch.updates) == 3
    assert len(batch.inserts) == 0
    assert len(batch.deletes) == 0


def test_deletes_routed_correctly():
    mapper = SearchProjectionMapper()
    batch = mapper.map([_change(IndexChangeType.RESOURCE_REMOVED)])
    assert len(batch.deletes) == 1
    assert len(batch.inserts) == 0
    assert len(batch.updates) == 0


def test_mixed_changes():
    mapper = SearchProjectionMapper()
    batch = mapper.map([
        _change(IndexChangeType.RESOURCE_ADDED, rid="r1"),
        _change(IndexChangeType.RESOURCE_UPDATED, rid="r2"),
        _change(IndexChangeType.RESOURCE_REMOVED, rid="r3"),
        _change(IndexChangeType.RESOURCE_RENAMED, rid="r4"),
        _change(IndexChangeType.RESOURCE_MOVED, rid="r5"),
    ])
    assert len(batch.inserts) == 1
    assert len(batch.updates) == 3
    assert len(batch.deletes) == 1
    assert batch.total == 5


def test_by_root_grouping():
    mapper = SearchProjectionMapper()
    batch = mapper.map([
        _change(IndexChangeType.RESOURCE_ADDED, rid="r1", root=1),
        _change(IndexChangeType.RESOURCE_ADDED, rid="r2", root=2),
        _change(IndexChangeType.RESOURCE_REMOVED, rid="r3", root=1),
        _change(IndexChangeType.RESOURCE_UPDATED, rid="r4", root=2),
    ])
    assert set(batch.by_root.keys()) == {1, 2}
    assert len(batch.by_root[1]) == 2
    assert len(batch.by_root[2]) == 2


def test_to_summary():
    mapper = SearchProjectionMapper()
    batch = mapper.map([
        _change(IndexChangeType.RESOURCE_ADDED, rid="r1"),
        _change(IndexChangeType.RESOURCE_UPDATED, rid="r2"),
        _change(IndexChangeType.RESOURCE_REMOVED, rid="r3"),
    ])
    s = batch.to_summary()
    assert s == {"inserts": 1, "updates": 1, "deletes": 1, "total": 3}


def test_map_single():
    mapper = SearchProjectionMapper()
    batch = mapper.map_single(_change(IndexChangeType.RESOURCE_ADDED))
    assert len(batch.inserts) == 1
    assert batch.total == 1


def test_deterministic_order():
    mapper = SearchProjectionMapper()
    changes = [
        _change(IndexChangeType.RESOURCE_ADDED, rid=f"r{i}")
        for i in range(10)
    ]
    b1 = mapper.map(list(changes))
    b2 = mapper.map(list(changes))
    assert [c.resource_id for c in b1.inserts] == [c.resource_id for c in b2.inserts]


def test_single_root_all_changes():
    mapper = SearchProjectionMapper()
    batch = mapper.map([
        _change(IndexChangeType.RESOURCE_ADDED, rid="r1", root=42),
        _change(IndexChangeType.RESOURCE_REMOVED, rid="r2", root=42),
    ])
    assert set(batch.by_root.keys()) == {42}
    assert batch.by_root[42][0].resource_id == "r1"
    assert batch.by_root[42][1].resource_id == "r2"