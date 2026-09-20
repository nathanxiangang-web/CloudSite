from __future__ import annotations

from cloudsite.modules.indexing.application.reconcile import (
    ReconcileService,
    WriteSummary,
)
from cloudsite.modules.indexing.domain.change import ChangeType
from cloudsite.modules.indexing.domain.snapshot import CategorySnapshot, SnapshotEntry
from cloudsite.modules.indexing.infrastructure.repository import IndexedEntry


class FakeIndexingStore:
    """In-memory IndexingStore that records all write calls for assertions."""

    def __init__(self, existing: list[IndexedEntry] | None = None) -> None:
        self._data: dict[str, IndexedEntry] = {
            e.resource_id: e for e in (existing or [])
        }
        self.upsert_calls: list[list[IndexedEntry]] = []
        self.remove_calls: list[list[str]] = []
        self.touch_calls: list[list[str]] = []

    async def list_indexed(self, *, category_id: str, provider_id: str) -> list[IndexedEntry]:
        return [
            e for e in self._data.values()
            if e.category_id == category_id and e.provider_id == provider_id
        ]

    async def upsert(self, entries: list[IndexedEntry]) -> int:
        self.upsert_calls.append(list(entries))
        for e in entries:
            self._data[e.resource_id] = e
        return len(entries)

    async def remove(self, resource_ids: list[str]) -> int:
        self.remove_calls.append(list(resource_ids))
        count = 0
        for rid in resource_ids:
            if rid in self._data:
                del self._data[rid]
                count += 1
        return count

    async def touch_unchanged(self, resource_ids: list[str]) -> int:
        self.touch_calls.append(list(resource_ids))
        return len(resource_ids)


def _snap_entry(rid: str, path: str = '/x', content_hash: str | None = 'h1') -> SnapshotEntry:
    return SnapshotEntry(resource_id=rid, path=path, name=rid, content_hash=content_hash)


def _indexed(rid: str, cat: str = 'cat', prov: str = 'prov', content_hash: str | None = 'h1') -> IndexedEntry:
    return IndexedEntry(
        resource_id=rid, category_id=cat, provider_id=prov,
        path='/x', name=rid, content_hash=content_hash,
    )


# --- zero-write when pagination_complete=False ---

async def test_no_removal_writes_when_pagination_incomplete():
    existing = [_indexed('old1'), _indexed('old2'), _indexed('old3')]
    store = FakeIndexingStore(existing=existing)
    service = ReconcileService(store)

    snapshot = CategorySnapshot(
        category_id='cat', provider_id='prov',
        entries=[_snap_entry('old1')],
        pagination_complete=False,
    )
    result = await service.reconcile(snapshot)

    assert store.remove_calls == []
    assert result.writes.removed == 0
    assert result.suppressed_removals == 2
    assert result.removal_writes_blocked is True


async def test_removals_written_when_pagination_complete():
    existing = [_indexed('old1'), _indexed('old2')]
    store = FakeIndexingStore(existing=existing)
    service = ReconcileService(store)

    snapshot = CategorySnapshot(
        category_id='cat', provider_id='prov',
        entries=[_snap_entry('old1')],
        pagination_complete=True,
    )
    result = await service.reconcile(snapshot)

    assert len(store.remove_calls) == 1
    assert 'old2' in store.remove_calls[0]
    assert result.writes.removed == 1
    assert result.suppressed_removals == 0


async def test_added_and_changed_still_written_when_incomplete():
    existing = [_indexed('keep', content_hash='h1')]
    store = FakeIndexingStore(existing=existing)
    service = ReconcileService(store)

    snapshot = CategorySnapshot(
        category_id='cat', provider_id='prov',
        entries=[
            _snap_entry('keep', content_hash='h2'),
            _snap_entry('new'),
        ],
        pagination_complete=False,
    )
    result = await service.reconcile(snapshot)

    assert result.writes.added == 1
    assert result.writes.changed == 1
    assert result.writes.removed == 0
    assert len(store.upsert_calls) == 1
    assert store.remove_calls == []


async def test_unchanged_entries_touched():
    existing = [_indexed('keep')]
    store = FakeIndexingStore(existing=existing)
    service = ReconcileService(store)

    snapshot = CategorySnapshot(
        category_id='cat', provider_id='prov',
        entries=[_snap_entry('keep')],
        pagination_complete=True,
    )
    result = await service.reconcile(snapshot)

    assert result.writes.unchanged == 1
    assert len(store.touch_calls) == 1


async def test_change_records_include_all_types():
    existing = [_indexed('keep'), _indexed('gone')]
    store = FakeIndexingStore(existing=existing)
    service = ReconcileService(store)

    snapshot = CategorySnapshot(
        category_id='cat', provider_id='prov',
        entries=[_snap_entry('keep'), _snap_entry('fresh')],
        pagination_complete=True,
    )
    result = await service.reconcile(snapshot)

    types = {c.change_type for c in result.changes}
    assert ChangeType.ADDED in types
    assert ChangeType.UNCHANGED in types
    assert ChangeType.REMOVED in types


async def test_empty_snapshot_complete_removes_all():
    existing = [_indexed('a'), _indexed('b')]
    store = FakeIndexingStore(existing=existing)
    service = ReconcileService(store)

    snapshot = CategorySnapshot(
        category_id='cat', provider_id='prov',
        entries=[], pagination_complete=True,
    )
    result = await service.reconcile(snapshot)

    assert result.writes.removed == 2
    assert len(store.remove_calls) == 1


async def test_empty_snapshot_incomplete_removes_nothing():
    existing = [_indexed('a'), _indexed('b')]
    store = FakeIndexingStore(existing=existing)
    service = ReconcileService(store)

    snapshot = CategorySnapshot(
        category_id='cat', provider_id='prov',
        entries=[], pagination_complete=False,
    )
    result = await service.reconcile(snapshot)

    assert result.writes.removed == 0
    assert store.remove_calls == []
    assert result.suppressed_removals == 2


async def test_write_summary_total_writes():
    ws = WriteSummary(added=3, changed=2, removed=1, unchanged=5)
    assert ws.total_writes == 6


async def test_no_changes_when_snapshot_matches_existing():
    existing = [_indexed('a'), _indexed('b')]
    store = FakeIndexingStore(existing=existing)
    service = ReconcileService(store)

    snapshot = CategorySnapshot(
        category_id='cat', provider_id='prov',
        entries=[_snap_entry('a'), _snap_entry('b')],
        pagination_complete=True,
    )
    result = await service.reconcile(snapshot)

    assert result.writes.added == 0
    assert result.writes.changed == 0
    assert result.writes.removed == 0
    assert result.writes.unchanged == 2
    assert store.remove_calls == []

async def test_reconcile_preserves_existing_id_when_snapshot_id_changes_for_same_path():
    existing = [
        IndexedEntry(
            resource_id="legacy-id",
            category_id="root:1",
            provider_id="prov",
            path="/same/file.zip",
            name="file.zip",
            size=10,
            metadata={
                "parent_id": "legacy-parent",
                "content_type": "file",
                "root_mapping_id": 1,
                "depth": 2,
                "child_folder_count": 0,
                "resource_count": 0,
                "extension": "zip",
                "mime_type": "application/zip",
                "thumbnail": "",
            },
        )
    ]
    store = FakeIndexingStore(existing=existing)
    service = ReconcileService(store)
    snapshot = CategorySnapshot(
        category_id="root:1",
        provider_id="prov",
        entries=[
            SnapshotEntry(
                resource_id="new-root-scoped-id",
                path="/same/file.zip",
                name="file.zip",
                size=10,
                metadata={
                    "parent_id": "legacy-parent",
                    "content_type": "file",
                    "root_mapping_id": 1,
                    "depth": 2,
                    "child_folder_count": 0,
                    "resource_count": 0,
                    "extension": "zip",
                    "mime_type": "application/zip",
                    "thumbnail": "",
                },
            )
        ],
        pagination_complete=True,
    )

    result = await service.reconcile(snapshot)

    assert result.writes.added == 0
    assert result.writes.removed == 0
    assert result.writes.unchanged == 1
    assert store.touch_calls == [["legacy-id"]]
    assert store.remove_calls == []


async def test_reconcile_remaps_new_child_parent_to_existing_folder_id():
    existing = [
        IndexedEntry(
            resource_id="legacy-folder",
            category_id="root:1",
            provider_id="prov",
            path="/same",
            name="same",
            metadata={
                "parent_id": None,
                "content_type": "file",
                "root_mapping_id": 1,
                "depth": 0,
                "child_folder_count": 0,
                "resource_count": 1,
                "extension": "",
                "mime_type": "",
                "thumbnail": "",
            },
        )
    ]
    store = FakeIndexingStore(existing=existing)
    service = ReconcileService(store)
    snapshot = CategorySnapshot(
        category_id="root:1",
        provider_id="prov",
        entries=[
            SnapshotEntry(
                resource_id="new-folder-id",
                path="/same",
                name="same",
                metadata={
                    "parent_id": None,
                    "content_type": "file",
                    "root_mapping_id": 1,
                    "depth": 0,
                    "child_folder_count": 0,
                    "resource_count": 1,
                    "extension": "",
                    "mime_type": "",
                    "thumbnail": "",
                },
            ),
            SnapshotEntry(
                resource_id="new-child-id",
                path="/same/new.zip",
                name="new.zip",
                size=5,
                metadata={
                    "parent_path": "/same",
                    "parent_id": "new-folder-id",
                    "content_type": "file",
                    "root_mapping_id": 1,
                    "depth": 1,
                    "child_folder_count": 0,
                    "resource_count": 0,
                    "extension": "zip",
                    "mime_type": "application/zip",
                    "thumbnail": "",
                },
            ),
        ],
        pagination_complete=True,
    )

    result = await service.reconcile(snapshot)

    assert result.writes.added == 1
    assert len(store.upsert_calls) == 1
    added = store.upsert_calls[0][0]
    assert added.resource_id == "new-child-id"
    assert added.metadata["parent_id"] == "legacy-folder"


async def test_reconcile_writes_metadata_only_changes():
    existing = [
        IndexedEntry(
            resource_id="folder",
            category_id="root:1",
            provider_id="prov",
            path="/folder",
            name="folder",
            metadata={
                "parent_id": None,
                "content_type": "file",
                "root_mapping_id": 1,
                "depth": 0,
                "child_folder_count": 0,
                "resource_count": 0,
                "extension": "",
                "mime_type": "",
                "thumbnail": "",
            },
        )
    ]
    store = FakeIndexingStore(existing=existing)
    service = ReconcileService(store)
    snapshot = CategorySnapshot(
        category_id="root:1",
        provider_id="prov",
        entries=[
            SnapshotEntry(
                resource_id="folder",
                path="/folder",
                name="folder",
                metadata={
                    "parent_id": None,
                    "content_type": "file",
                    "root_mapping_id": 1,
                    "depth": 0,
                    "child_folder_count": 1,
                    "resource_count": 2,
                    "extension": "",
                    "mime_type": "",
                    "thumbnail": "",
                },
            )
        ],
        pagination_complete=True,
    )

    result = await service.reconcile(snapshot)

    assert result.writes.changed == 1
    assert store.upsert_calls[0][0].metadata["child_folder_count"] == 1
    assert store.upsert_calls[0][0].metadata["resource_count"] == 2


async def test_reconcile_ignores_folder_only_metadata_for_resources():
    metadata = {
        "is_dir": False,
        "parent_id": "folder",
        "content_type": "file",
        "root_mapping_id": 1,
        "extension": "zip",
        "mime_type": "application/zip",
        "thumbnail": "",
    }
    existing = [
        IndexedEntry(
            resource_id="resource",
            category_id="root:1",
            provider_id="prov",
            path="/folder/file.zip",
            name="file.zip",
            size=10,
            metadata={**metadata, "depth": 0},
        )
    ]
    store = FakeIndexingStore(existing=existing)
    service = ReconcileService(store)
    snapshot = CategorySnapshot(
        category_id="root:1",
        provider_id="prov",
        entries=[
            SnapshotEntry(
                resource_id="resource",
                path="/folder/file.zip",
                name="file.zip",
                size=10,
                metadata={**metadata, "depth": 3},
            )
        ],
        pagination_complete=True,
    )

    result = await service.reconcile(snapshot)

    assert result.writes.changed == 0
    assert result.writes.unchanged == 1
