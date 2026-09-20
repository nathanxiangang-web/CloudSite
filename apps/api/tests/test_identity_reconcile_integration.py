"""R4 PR02: Identity integration into reconcile (V2 doc 22-23).

Exercises ReconcileService.reconcile_with_identity to verify that identity
matching takes priority over path matching, rename/move preserve resource_id,
conflicts are reported explicitly, new entries record identity history, and
cross-root moves do not preserve identity.
"""
from __future__ import annotations

from datetime import datetime, timezone

from cloudsite.modules.indexing.application.reconcile import ReconcileService
from cloudsite.modules.indexing.domain.change import ChangeType
from cloudsite.modules.indexing.domain.identity import (
    IdentityFingerprint,
    IdentityMatchingEngine,
    IdentityRecord,
)
from cloudsite.modules.indexing.domain.snapshot import CategorySnapshot, SnapshotEntry
from cloudsite.modules.indexing.infrastructure.repository import IndexedEntry

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
CAT = "root:1"
PROV = "prov"


def _fingerprint(entry: Any) -> IdentityFingerprint:
    """Extract fingerprint with root_mapping_id read from metadata.

    Mirrors reconcile._entry_fingerprint so seeded history digests match the
    digests computed during reconcile.
    """
    meta = getattr(entry, "metadata", None) or {}
    return IdentityFingerprint(
        name=str(getattr(entry, "name", "") or ""),
        size=getattr(entry, "size", None),
        modified_at=getattr(entry, "modified_at", None),
        root_mapping_id=int(meta.get("root_mapping_id", 0) or 0),
        path=getattr(entry, "path", None),
    )


class FakeIndexingStore:
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


class FakeIdentityRepository:
    """In-memory identity history repository for tests."""

    def __init__(self) -> None:
        self._records: dict[str, IdentityRecord] = {}
        self.save_calls: list[tuple[str, IdentityFingerprint]] = []

    async def ensure_table(self) -> None:
        return None

    async def find_by_fingerprint(
        self, fingerprint: IdentityFingerprint,
    ) -> list[IdentityRecord]:
        return [
            rec for rec in self._records.values()
            if rec.root_mapping_id == fingerprint.root_mapping_id
            and rec.fingerprint == fingerprint.digest
        ]

    async def save(
        self, resource_id: str, fingerprint: IdentityFingerprint,
        *, now: datetime | None = None,
    ) -> None:
        self.save_calls.append((resource_id, fingerprint))
        ts = now or datetime.now(timezone.utc)
        existing = self._records.get(resource_id)
        first_seen = existing.first_seen_at if existing else ts
        self._records[resource_id] = IdentityRecord(
            resource_id=resource_id,
            fingerprint=fingerprint.digest,
            root_mapping_id=fingerprint.root_mapping_id,
            name=fingerprint.name,
            path=fingerprint.path,
            size=fingerprint.size,
            modified_at=fingerprint.modified_at,
            first_seen_at=first_seen,
            last_seen_at=ts,
            status="active",
        )

    async def find_by_resource_id(self, resource_id: str) -> IdentityRecord | None:
        return self._records.get(resource_id)

    async def delete_by_resource_id(self, resource_id: str) -> None:
        self._records.pop(resource_id, None)

    def seed(
        self, resource_id: str, fingerprint: IdentityFingerprint,
        *, path: str | None = None,
    ) -> IdentityRecord:
        record = IdentityRecord(
            resource_id=resource_id,
            fingerprint=fingerprint.digest,
            root_mapping_id=fingerprint.root_mapping_id,
            name=fingerprint.name,
            path=path if path is not None else fingerprint.path,
            size=fingerprint.size,
            modified_at=fingerprint.modified_at,
            first_seen_at=NOW,
            last_seen_at=NOW,
            status="active",
        )
        self._records[resource_id] = record
        return record


def _meta(root_mapping_id: int = 1, is_dir: bool = False) -> dict:
    return {
        "root_mapping_id": root_mapping_id,
        "is_dir": is_dir,
        "parent_id": None,
        "content_type": "file",
        "extension": "zip",
        "mime_type": "application/zip",
        "thumbnail": "",
    }


def _snap(
    rid: str, path: str, name: str, size: int = 1024,
    modified_at: datetime | None = NOW, root_mapping_id: int = 1,
) -> SnapshotEntry:
    return SnapshotEntry(
        resource_id=rid, path=path, name=name, size=size,
        modified_at=modified_at, metadata=_meta(root_mapping_id),
    )


def _indexed(
    rid: str, path: str, name: str, size: int = 1024,
    modified_at: datetime | None = NOW, root_mapping_id: int = 1,
    cat: str = CAT, prov: str = PROV,
) -> IndexedEntry:
    return IndexedEntry(
        resource_id=rid, category_id=cat, provider_id=prov,
        path=path, name=name, size=size, modified_at=modified_at,
        metadata=_meta(root_mapping_id),
    )


def _build(store: FakeIndexingStore, repo: FakeIdentityRepository):
    return ReconcileService(store), IdentityMatchingEngine(), repo


# --- test 1: rename preserves id + updates path ---

async def test_reconcile_with_identity_rename():
    existing = [_indexed("res-A", "/root/A.zip", "A.zip", size=4096)]
    store = FakeIndexingStore(existing=existing)
    repo = FakeIdentityRepository()
    engine = IdentityMatchingEngine()
    original_fp = _fingerprint(_snap("res-A", "/root/A.zip", "A.zip", size=4096))
    repo.seed("res-A", original_fp, path="/root/A.zip")

    service = ReconcileService(store)
    snapshot = CategorySnapshot(
        category_id=CAT, provider_id=PROV,
        entries=[_snap("new-id", "/root/B.zip", "B.zip", size=4096)],
        pagination_complete=True,
    )
    result = await service.reconcile_with_identity(snapshot, engine, repo)

    rename_changes = [c for c in result.changes if c.change_type is ChangeType.RENAMED]
    assert len(rename_changes) == 1
    assert rename_changes[0].resource_id == "res-A"
    assert rename_changes[0].after["path"] == "/root/B.zip"
    assert rename_changes[0].before["path"] == "/root/A.zip"
    assert result.writes.changed == 1
    assert store.upsert_calls
    assert store.upsert_calls[0][0].resource_id == "res-A"
    assert store.upsert_calls[0][0].path == "/root/B.zip"


# --- test 2: move preserves id + updates path ---

async def test_reconcile_with_identity_move():
    existing = [_indexed("res-A", "/root/A.zip", "A.zip", size=4096)]
    store = FakeIndexingStore(existing=existing)
    repo = FakeIdentityRepository()
    engine = IdentityMatchingEngine()
    original_fp = _fingerprint(_snap("res-A", "/root/A.zip", "A.zip", size=4096))
    repo.seed("res-A", original_fp, path="/root/A.zip")

    service = ReconcileService(store)
    snapshot = CategorySnapshot(
        category_id=CAT, provider_id=PROV,
        entries=[_snap("new-id", "/root/sub/A.zip", "A.zip", size=4096)],
        pagination_complete=True,
    )
    result = await service.reconcile_with_identity(snapshot, engine, repo)

    move_changes = [c for c in result.changes if c.change_type is ChangeType.MOVED]
    assert len(move_changes) == 1
    assert move_changes[0].resource_id == "res-A"
    assert move_changes[0].after["path"] == "/root/sub/A.zip"
    assert move_changes[0].before["path"] == "/root/A.zip"
    assert store.upsert_calls[0][0].resource_id == "res-A"
    assert store.upsert_calls[0][0].path == "/root/sub/A.zip"


# --- test 3: conflict reported explicitly ---

async def test_reconcile_with_identity_conflict():
    store = FakeIndexingStore()
    repo = FakeIdentityRepository()
    engine = IdentityMatchingEngine()
    fp = _fingerprint(_snap("x", "/root/A.zip", "A.zip", size=500))
    repo.seed("res-a", fp, path="/root/A.zip")
    repo.seed("res-b", fp, path="/root/other/A.zip")

    service = ReconcileService(store)
    snapshot = CategorySnapshot(
        category_id=CAT, provider_id=PROV,
        entries=[_snap("incoming", "/root/A.zip", "A.zip", size=500)],
        pagination_complete=True,
    )
    result = await service.reconcile_with_identity(snapshot, engine, repo)

    assert result.has_conflicts
    assert len(result.conflicts) == 1
    assert result.conflicts[0].change_type is ChangeType.CONFLICT
    assert result.writes.added == 0
    assert result.writes.changed == 0
    assert store.upsert_calls == []


# --- test 4: new entry -> ADDED + history recorded ---

async def test_reconcile_with_identity_new():
    store = FakeIndexingStore()
    repo = FakeIdentityRepository()
    service, engine, _ = _build(store, repo)

    snapshot = CategorySnapshot(
        category_id=CAT, provider_id=PROV,
        entries=[_snap("brand-new", "/root/new.zip", "new.zip", size=777)],
        pagination_complete=True,
    )
    result = await service.reconcile_with_identity(snapshot, engine, repo)

    added = [c for c in result.changes if c.change_type is ChangeType.ADDED]
    assert len(added) == 1
    assert added[0].resource_id == "brand-new"
    assert result.identity_history_updated is True
    saved = await repo.find_by_resource_id("brand-new")
    assert saved is not None
    assert saved.path == "/root/new.zip"


# --- test 5: identity match takes priority over path match ---

async def test_reconcile_identity_before_path_match():
    existing = [
        _indexed("res-A", "/old/A.zip", "A.zip", size=4096),
        _indexed("res-B", "/new/A.zip", "A.zip", size=4096),
    ]
    store = FakeIndexingStore(existing=existing)
    repo = FakeIdentityRepository()
    engine = IdentityMatchingEngine()
    fp_a = _fingerprint(_snap("res-A", "/old/A.zip", "A.zip", size=4096))
    repo.seed("res-A", fp_a, path="/old/A.zip")

    service = ReconcileService(store)
    snapshot = CategorySnapshot(
        category_id=CAT, provider_id=PROV,
        entries=[_snap("snap-id", "/new/A.zip", "A.zip", size=4096)],
        pagination_complete=True,
    )
    result = await service.reconcile_with_identity(snapshot, engine, repo)

    move_changes = [c for c in result.changes if c.change_type is ChangeType.MOVED]
    assert len(move_changes) == 1
    assert move_changes[0].resource_id == "res-A"
    assert move_changes[0].after["path"] == "/new/A.zip"
    assert not any(c.resource_id == "res-B" and c.change_type is ChangeType.UNCHANGED
                   for c in result.changes)


# --- test 6: no identity engine -> fallback to path match ---

async def test_reconcile_no_identity_engine_fallback():
    existing = [_indexed("legacy-id", "/same/file.zip", "file.zip", size=10)]
    store = FakeIndexingStore(existing=existing)
    service = ReconcileService(store)

    snapshot = CategorySnapshot(
        category_id=CAT, provider_id=PROV,
        entries=[_snap("new-scoped-id", "/same/file.zip", "file.zip", size=10)],
        pagination_complete=True,
    )
    result = await service.reconcile_with_identity(snapshot, None, None)

    assert result.writes.unchanged == 1
    assert result.writes.added == 0
    assert result.writes.removed == 0
    assert store.touch_calls == [["legacy-id"]]
    assert result.identity_history_updated is False


# --- test 7: identity history updated after reconcile ---

async def test_reconcile_identity_history_updated():
    existing = [_indexed("res-A", "/root/A.zip", "A.zip", size=256)]
    store = FakeIndexingStore(existing=existing)
    repo = FakeIdentityRepository()
    engine = IdentityMatchingEngine()
    fp = _fingerprint(_snap("res-A", "/root/A.zip", "A.zip", size=256))
    repo.seed("res-A", fp, path="/root/A.zip")

    service = ReconcileService(store)
    snapshot = CategorySnapshot(
        category_id=CAT, provider_id=PROV,
        entries=[
            _snap("res-A", "/root/B.zip", "B.zip", size=256),
            _snap("res-new", "/root/C.zip", "C.zip", size=999),
        ],
        pagination_complete=True,
    )
    result = await service.reconcile_with_identity(snapshot, engine, repo)

    assert result.identity_history_updated is True
    rec_a = await repo.find_by_resource_id("res-A")
    assert rec_a is not None
    assert rec_a.path == "/root/B.zip"
    rec_new = await repo.find_by_resource_id("res-new")
    assert rec_new is not None
    assert rec_new.path == "/root/C.zip"


# --- test 8: cross-root move does not preserve identity ---

async def test_reconcile_cross_root_no_identity():
    existing = [_indexed("res-A", "/root1/A.zip", "A.zip", size=4096, root_mapping_id=1)]
    store = FakeIndexingStore(existing=existing)
    repo = FakeIdentityRepository()
    engine = IdentityMatchingEngine()
    fp = _fingerprint(
        _snap("res-A", "/root1/A.zip", "A.zip", size=4096, root_mapping_id=1)
    )
    repo.seed("res-A", fp, path="/root1/A.zip")

    service = ReconcileService(store)
    snapshot = CategorySnapshot(
        category_id=CAT, provider_id=PROV,
        entries=[_snap("cross-id", "/root2/A.zip", "A.zip", size=4096, root_mapping_id=2)],
        pagination_complete=True,
    )
    result = await service.reconcile_with_identity(snapshot, engine, repo)

    added = [c for c in result.changes if c.change_type is ChangeType.ADDED]
    assert len(added) == 1
    assert added[0].resource_id == "cross-id"
    assert not any(c.change_type is ChangeType.MOVED for c in result.changes)
    assert not any(c.change_type is ChangeType.RENAMED for c in result.changes)
    assert store.upsert_calls[0][0].resource_id == "cross-id"
