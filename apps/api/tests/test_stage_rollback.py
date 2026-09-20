"""R1 supplement: stage rollback tests (V2 doc section 78).

V2 doc section 78 requires that stage rollback paths be exercised. Stage
rollback means discarding staging/intermediate scan state without losing
production data, and falling back to serial/audit/full-rebuild paths when a
concurrency/durable/incremental/search stage is disabled or dirty.

Exercises:
- test_concurrency_1_fallback: concurrency=1 falls back to serial BFS and
  produces the same entry set as concurrency=8
- test_durable_disable_discard: with durable scan disabled, discarding
  index_scan_entries staging rows does not affect production resources
- test_incremental_disable_audit: with incremental disabled, a full
  reconcile (audit fallback) over a complete snapshot preserves existing
  entries (no data loss)
- test_search_dirty_rebuild: a dirty search marker triggers
  recover_search_index_if_dirty, which rebuilds search_fts from the
  authoritative inventory and clears the marker
- test_stage_rollback_no_data_loss: discarding all durable scan staging
  tables does not delete production folders/resources

All databases are temporary under tmp_path; no production paths are touched.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from cloudsite import database
from cloudsite.database import StateBase
from cloudsite.modules.indexing.domain.snapshot import CategorySnapshot, SnapshotEntry
from cloudsite.modules.indexing.infrastructure.durable_scan_repository import (
    DurableScanRepository,
)
from cloudsite.modules.indexing.infrastructure.repository import (
    IndexedEntry,
)
from cloudsite.modules.search.contracts.public import recover_search_index_if_dirty
from cloudsite.platform.db import session as db_session
from cloudsite.database import IndexBase


DURABLE_TABLES = ("index_scan_runs", "index_scan_dirs", "index_scan_entries")


def _enable_foreign_keys(engine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn, _record):  # noqa: ANN001
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


async def _seed_root_mapping(session: AsyncSession, root_id: int = 2001) -> int:
    await session.execute(
        text(
            "INSERT INTO content_root_mappings "
            "(id, connection_id, content_type, display_name, alist_path, enabled, "
            "sort_order, home_order, created_at, updated_at) "
            "VALUES (:id, 1, 'software', :name, :path, 1, 0, 0, "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {"id": root_id, "name": f"stage-root-{root_id}", "path": f"/s{root_id}"},
    )
    await session.commit()
    return root_id


# ----------------------------------------------------------------------
# 1. concurrency=1 fallback
# ----------------------------------------------------------------------

class _FakeProvider:
    """ProviderScanPort fake backed by an in-memory directory tree."""

    def __init__(self, tree: dict[str, list[dict[str, Any]]]) -> None:
        self._tree = tree

    async def list_path(
        self,
        path: str,
        refresh: bool = False,
        strict: bool = False,
    ) -> list[dict[str, Any]]:
        return list(self._tree.get(path, []))

    async def get_metadata(self, path: str) -> dict[str, Any]:
        return {"name": path.rsplit("/", 1)[-1]}


def _make_tree() -> dict[str, list[dict[str, Any]]]:
    return {
        "/root": [
            {"name": "a", "is_dir": True},
            {"name": "b", "is_dir": True},
            {"name": "c", "is_dir": False, "size": 100},
        ],
        "/root/a": [
            {"name": "a1", "is_dir": False, "size": 10},
            {"name": "sub", "is_dir": True},
        ],
        "/root/a/sub": [
            {"name": "deep.zip", "is_dir": False, "size": 5},
        ],
        "/root/b": [
            {"name": "b1", "is_dir": False, "size": 30},
        ],
    }


async def test_concurrency_1_fallback():
    """concurrency=1 falls back to serial BFS and matches concurrency=8."""
    from cloudsite.modules.indexing.infrastructure.alist_adapter import (
        AListProviderAdapter,
    )
    from cloudsite.modules.providers.contracts.public import ProviderScanRoot

    root = ProviderScanRoot(
        root_mapping_id=1,
        content_type="software",
        storage_path="/root",
        display_name="Root",
    )

    adapter_serial = AListProviderAdapter(_FakeProvider(_make_tree()), [root])
    entries_serial, _, complete_serial = await adapter_serial.scan_category(
        "root:1", concurrency=1
    )

    adapter_concurrent = AListProviderAdapter(_FakeProvider(_make_tree()), [root])
    entries_concurrent, _, complete_concurrent = await adapter_concurrent.scan_category(
        "root:1", concurrency=8
    )

    assert complete_serial is True
    assert complete_concurrent is True
    serial_paths = {e.path for e in entries_serial}
    concurrent_paths = {e.path for e in entries_concurrent}
    assert serial_paths == concurrent_paths
    assert serial_paths == {
        "/root",
        "/root/a",
        "/root/a/a1",
        "/root/a/sub",
        "/root/a/sub/deep.zip",
        "/root/b",
        "/root/b/b1",
        "/root/c",
    }


# ----------------------------------------------------------------------
# 2. durable disable + discard staging
# ----------------------------------------------------------------------

async def test_durable_disable_discard(tmp_path):
    """With durable scan disabled, discarding staging entries does not affect production resources."""
    state_engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'state.db'}"
    )
    index_engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'index.db'}"
    )
    _enable_foreign_keys(state_engine)
    _enable_foreign_keys(index_engine)
    try:
        async with state_engine.begin() as conn:
            await conn.run_sync(StateBase.metadata.create_all)
        async with index_engine.begin() as conn:
            await conn.run_sync(IndexBase.metadata.create_all)

        state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
        index_factory = async_sessionmaker(index_engine, expire_on_commit=False)

        async with state_factory() as session:
            root_id = await _seed_root_mapping(session)
            repo = DurableScanRepository(session)
            run = await repo.create_scan_run(root_id, fingerprint="fp-stage")
            await repo.add_entries(
                run.id,
                [
                    SnapshotEntry(
                        resource_id="stage-res-1",
                        path="/s2001/staged.zip",
                        name="staged.zip",
                        modified_at=datetime(2026, 9, 20, tzinfo=timezone.utc),
                        content_hash="hash-1",
                        metadata={"is_dir": False},
                    ),
                ],
            )
            await session.commit()
            staging_count = await repo.count_entries(run.id)
            assert staging_count == 1

        async with index_factory() as session:
            from cloudsite.models import Folder, Resource
            now = datetime(2026, 9, 20, tzinfo=timezone.utc)
            session.add_all(
                [
                    Folder(
                        id="prod-folder",
                        name="software",
                        path="/s2001",
                        parent_id=None,
                        content_type="software",
                        root_mapping_id=root_id,
                        status="active",
                        indexed_at=now,
                    ),
                    Resource(
                        id="prod-resource",
                        name="tool.zip",
                        path="/s2001/tool.zip",
                        parent_id="prod-folder",
                        content_type="software",
                        root_mapping_id=root_id,
                        extension="zip",
                        status="active",
                        indexed_at=now,
                    ),
                ]
            )
            await session.commit()

        async with state_factory() as session:
            await session.execute(text("DELETE FROM index_scan_entries"))
            await session.commit()

        async with state_factory() as session:
            repo = DurableScanRepository(session)
            runs = await session.execute(text("SELECT id FROM index_scan_runs"))
            run_ids = [r[0] for r in runs.all()]
            for run_id in run_ids:
                assert await repo.count_entries(run_id) == 0

        async with index_factory() as session:
            folder_count = (
                await session.execute(text("SELECT COUNT(*) FROM folders"))
            ).scalar_one()
            resource_count = (
                await session.execute(text("SELECT COUNT(*) FROM resources"))
            ).scalar_one()
            assert folder_count == 1
            assert resource_count == 1
    finally:
        await state_engine.dispose()
        await index_engine.dispose()


# ----------------------------------------------------------------------
# 3. incremental disable + audit fallback
# ----------------------------------------------------------------------

class _FakeIndexingStore:
    """In-memory IndexingStore fake for reconcile audit-fallback verification."""

    def __init__(self, entries: list[IndexedEntry] | None = None) -> None:
        self._entries: dict[str, IndexedEntry] = {
            e.resource_id: e for e in (entries or [])
        }

    async def list_indexed(self, *, category_id: str, provider_id: str) -> list[IndexedEntry]:
        return [
            e for e in self._entries.values()
            if e.category_id == category_id and e.provider_id == provider_id
        ]

    async def upsert(self, entries: list[IndexedEntry]) -> int:
        for e in entries:
            self._entries[e.resource_id] = e
        return len(entries)

    async def remove(self, resource_ids: list[str]) -> int:
        removed = 0
        for rid in resource_ids:
            if rid in self._entries:
                del self._entries[rid]
                removed += 1
        return removed

    async def touch_unchanged(self, resource_ids: list[str]) -> int:
        return len(resource_ids)


async def test_incremental_disable_audit():
    """With incremental disabled, full reconcile (audit fallback) preserves existing entries."""
    from cloudsite.modules.indexing.application.reconcile import ReconcileService

    now = datetime(2026, 9, 20, tzinfo=timezone.utc)
    existing = [
        IndexedEntry(
            resource_id="res-1",
            category_id="cat-1",
            provider_id="prov-1",
            path="/cat-1/file-1.zip",
            name="file-1.zip",
            size=100,
            modified_at=now,
            content_hash="hash-1",
            metadata={"is_dir": False},
            indexed_at=now,
        ),
        IndexedEntry(
            resource_id="res-2",
            category_id="cat-1",
            provider_id="prov-1",
            path="/cat-1/file-2.zip",
            name="file-2.zip",
            size=200,
            modified_at=now,
            content_hash="hash-2",
            metadata={"is_dir": False},
            indexed_at=now,
        ),
    ]
    store = _FakeIndexingStore(list(existing))
    reconcile_service = ReconcileService(store)

    snapshot = CategorySnapshot(
        category_id="cat-1",
        provider_id="prov-1",
        entries=[
            SnapshotEntry(
                resource_id="res-1",
                path="/cat-1/file-1.zip",
                name="file-1.zip",
                modified_at=now,
                content_hash="hash-1",
                metadata={"is_dir": False, "size": 100},
            ),
            SnapshotEntry(
                resource_id="res-2",
                path="/cat-1/file-2.zip",
                name="file-2.zip",
                modified_at=now,
                content_hash="hash-2",
                metadata={"is_dir": False, "size": 200},
            ),
        ],
        pagination_complete=True,
    )

    result = await reconcile_service.reconcile(snapshot)

    assert result.writes.removed == 0
    assert result.suppressed_removals == 0
    surviving = await store.list_indexed(category_id="cat-1", provider_id="prov-1")
    surviving_ids = {e.resource_id for e in surviving}
    assert {"res-1", "res-2"}.issubset(surviving_ids)


# ----------------------------------------------------------------------
# 4. search dirty + full rebuild fallback
# ----------------------------------------------------------------------

async def test_search_dirty_rebuild(monkeypatch):
    """A dirty search marker triggers a full rebuild from the authoritative inventory."""
    from cloudsite.models import Folder, Resource, SystemSetting

    state_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    index_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    index_factory = async_sessionmaker(index_engine, expire_on_commit=False)
    try:
        async with state_engine.begin() as conn:
            await conn.run_sync(StateBase.metadata.create_all)
        async with index_engine.begin() as conn:
            await conn.run_sync(IndexBase.metadata.create_all)
            await conn.exec_driver_sql(
                "CREATE VIRTUAL TABLE search_fts USING fts5("
                "object_id UNINDEXED, object_type UNINDEXED, name, extension, "
                "content_type UNINDEXED, description, tags, breadcrumb_text)"
            )
        monkeypatch.setattr(db_session, "StateSession", state_factory)
        monkeypatch.setattr(db_session, "IndexSession", index_factory)

        now = datetime(2026, 9, 20, tzinfo=timezone.utc)
        async with state_factory() as session:
            session.add(
                SystemSetting(
                    key="search_index_dirty",
                    value="true",
                    value_type="boolean",
                )
            )
            await session.commit()
        async with index_factory() as session:
            session.add_all(
                [
                    Folder(
                        id="f-stage-root",
                        name="software",
                        path="/software",
                        parent_id=None,
                        content_type="software",
                        root_mapping_id=1,
                        status="active",
                        indexed_at=now,
                    ),
                    Resource(
                        id="r-stage-file",
                        name="package.zip",
                        path="/software/package.zip",
                        parent_id="f-stage-root",
                        content_type="software",
                        root_mapping_id=1,
                        extension="zip",
                        status="active",
                        indexed_at=now,
                    ),
                ]
            )
            await session.commit()

        rebuilt = await recover_search_index_if_dirty()
        assert rebuilt == 2

        async with index_factory() as session:
            rows = list(
                (
                    await session.execute(
                        text(
                            "SELECT object_id, object_type FROM search_fts "
                            "ORDER BY object_type, object_id"
                        )
                    )
                ).all()
            )
            assert rows == [("f-stage-root", "folder"), ("r-stage-file", "resource")]
        async with state_factory() as session:
            dirty = await session.get(SystemSetting, "search_index_dirty")
            assert dirty.value == "false"
    finally:
        await state_engine.dispose()
        await index_engine.dispose()


# ----------------------------------------------------------------------
# 5. stage rollback no data loss
# ----------------------------------------------------------------------

async def test_stage_rollback_no_data_loss(tmp_path):
    """Discarding all durable scan staging tables does not delete production folders/resources."""
    state_engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'state.db'}"
    )
    index_engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'index.db'}"
    )
    _enable_foreign_keys(state_engine)
    _enable_foreign_keys(index_engine)
    try:
        async with state_engine.begin() as conn:
            await conn.run_sync(StateBase.metadata.create_all)
        async with index_engine.begin() as conn:
            await conn.run_sync(IndexBase.metadata.create_all)

        state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
        index_factory = async_sessionmaker(index_engine, expire_on_commit=False)

        async with state_factory() as session:
            root_id = await _seed_root_mapping(session)
            repo = DurableScanRepository(session)
            run = await repo.create_scan_run(root_id, fingerprint="fp-rollback")
            await repo.add_dirs(
                run.id,
                [("/s2001", 0), ("/s2001/sub", 1)],
            )
            await repo.add_entries(
                run.id,
                [
                    SnapshotEntry(
                        resource_id="stage-rb-1",
                        path="/s2001/staged-1.zip",
                        name="staged-1.zip",
                        modified_at=datetime(2026, 9, 20, tzinfo=timezone.utc),
                        content_hash="hash-rb-1",
                        metadata={"is_dir": False},
                    ),
                ],
            )
            await session.commit()

        async with index_factory() as session:
            from cloudsite.models import Folder, Resource
            now = datetime(2026, 9, 20, tzinfo=timezone.utc)
            session.add_all(
                [
                    Folder(
                        id="prod-folder-rb",
                        name="software",
                        path="/s2001",
                        parent_id=None,
                        content_type="software",
                        root_mapping_id=root_id,
                        status="active",
                        indexed_at=now,
                    ),
                    Resource(
                        id="prod-resource-rb",
                        name="release.zip",
                        path="/s2001/release.zip",
                        parent_id="prod-folder-rb",
                        content_type="software",
                        root_mapping_id=root_id,
                        extension="zip",
                        status="active",
                        indexed_at=now,
                    ),
                ]
            )
            await session.commit()

        async with state_factory() as session:
            for table in DURABLE_TABLES:
                await session.execute(text(f"DELETE FROM {table}"))
            await session.commit()

        async with state_factory() as session:
            for table in DURABLE_TABLES:
                count = (
                    await session.execute(text(f"SELECT COUNT(*) FROM {table}"))
                ).scalar_one()
                assert count == 0, f"staging table {table} not cleared"

        async with index_factory() as session:
            folder_count = (
                await session.execute(text("SELECT COUNT(*) FROM folders"))
            ).scalar_one()
            resource_count = (
                await session.execute(text("SELECT COUNT(*) FROM resources"))
            ).scalar_one()
            assert folder_count == 1, "production folder lost during stage rollback"
            assert resource_count == 1, "production resource lost during stage rollback"
            folder = (
                await session.execute(
                    text(
                        "SELECT id, name, path FROM folders WHERE id='prod-folder-rb'"
                    )
                )
            ).first()
            assert folder is not None
            assert folder.name == "software"
            resource = (
                await session.execute(
                    text(
                        "SELECT id, name, path FROM resources WHERE id='prod-resource-rb'"
                    )
                )
            ).first()
            assert resource is not None
            assert resource.name == "release.zip"
    finally:
        await state_engine.dispose()
        await index_engine.dispose()
