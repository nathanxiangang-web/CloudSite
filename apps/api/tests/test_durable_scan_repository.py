"""R2 PR02: DurableScanRepository CRUD tests (V2 doc sections 11-13).

Exercises the repository layer over the three durable scan-progress tables
introduced in R2 PR01. All tests use temporary SQLite databases with
PRAGMA foreign_keys=ON so cascade-delete and FK semantics match production.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from cloudsite.models import IndexScanDir, IndexScanEntry, IndexScanRun
from cloudsite.modules.indexing.domain.snapshot import SnapshotEntry
from cloudsite.modules.indexing.infrastructure.durable_scan_repository import (
    DurableScanRepository,
)
from cloudsite.platform.db import StateBase


def _enable_foreign_keys(engine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn, _record):  # noqa: ANN001
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


async def _make_engine(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'state.db'}",
    )
    _enable_foreign_keys(engine)
    async with engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, factory


async def _seed_root_mapping(session: AsyncSession, root_id: int = 1001) -> int:
    await session.execute(
        text(
            "INSERT INTO content_root_mappings "
            "(id, connection_id, content_type, display_name, alist_path, enabled, "
            "sort_order, home_order, created_at, updated_at) "
            "VALUES (:id, 1, 'software', :name, :path, 1, 0, 0, "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {"id": root_id, "name": f"root-{root_id}", "path": f"/r{root_id}"},
    )
    await session.commit()
    return root_id


async def test_create_and_get_scan_run(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
            repo = DurableScanRepository(session)
            created = await repo.create_scan_run(root_id, fingerprint="fp-1")
            assert created.id is not None
            assert created.root_mapping_id == root_id
            assert created.status == "pending"
            assert created.fingerprint == "fp-1"

            fetched = await repo.get_scan_run(created.id)
            assert fetched is not None
            assert fetched.id == created.id
            assert fetched.status == "pending"

        async with factory() as session:
            repo = DurableScanRepository(session)
            missing = await repo.get_scan_run(str(uuid.uuid4()))
            assert missing is None
    finally:
        await engine.dispose()


async def test_update_scan_run_status(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
            repo = DurableScanRepository(session)
            created = await repo.create_scan_run(root_id)
            await session.commit()

            await repo.update_scan_run_status(created.id, "running")
            await session.commit()

        async with factory() as session:
            repo = DurableScanRepository(session)
            run = await repo.get_scan_run(created.id)
            assert run is not None
            assert run.status == "running"
            assert run.finished_at is None

            await repo.update_scan_run_status(
                created.id,
                "completed",
                total_dirs=4,
                total_entries=12,
            )
            await session.commit()

        async with factory() as session:
            repo = DurableScanRepository(session)
            run = await repo.get_scan_run(created.id)
            assert run is not None
            assert run.status == "completed"
            assert run.total_dirs == 4
            assert run.total_entries == 12
            assert run.finished_at is not None

        async with factory() as session:
            repo = DurableScanRepository(session)
            with pytest.raises(ValueError):
                await repo.update_scan_run_status(
                    created.id, "failed", bogus_field=1
                )
    finally:
        await engine.dispose()


async def test_get_active_scan_run(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
            repo = DurableScanRepository(session)
            pending = await repo.create_scan_run(root_id)
            running = await repo.create_scan_run(root_id)
            await session.commit()

            await repo.update_scan_run_status(running.id, "running")
            await session.commit()

        async with factory() as session:
            repo = DurableScanRepository(session)
            active = await repo.get_active_scan_run(root_id)
            assert active is not None
            assert active.id == running.id
            assert active.status == "running"

            runs = await repo.list_scan_runs(root_id)
            assert len(runs) == 2
            assert {r.id for r in runs} == {pending.id, running.id}

            none_active = await repo.get_active_scan_run(999999)
            assert none_active is None
    finally:
        await engine.dispose()


async def test_add_and_claim_dirs(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
            repo = DurableScanRepository(session)
            run = await repo.create_scan_run(root_id)
            await session.commit()

            await repo.add_dirs(
                run.id,
                [("/", 0), ("/a", 1), ("/b", 1)],
            )
            await session.commit()

            assert await repo.count_dirs(run.id) == 3
            assert await repo.count_dirs(run.id, "pending") == 3
            assert await repo.count_dirs(run.id, "running") == 0

            claimed = await repo.claim_next_dir(run.id)
            assert claimed is not None
            assert claimed.status == "running"
            assert claimed.path == "/"
            await session.commit()

        async with factory() as session:
            repo = DurableScanRepository(session)
            assert await repo.count_dirs(run.id, "running") == 1
            assert await repo.count_dirs(run.id, "pending") == 2

            second = await repo.claim_next_dir(run.id)
            third = await repo.claim_next_dir(run.id)
            fourth = await repo.claim_next_dir(run.id)
            await session.commit()

        async with factory() as session:
            repo = DurableScanRepository(session)
            assert second is not None and third is not None
            assert second.id != claimed.id
            assert third.id != claimed.id
            assert second.id != third.id
            assert fourth is None
            assert await repo.count_dirs(run.id, "running") == 3
            assert await repo.count_dirs(run.id, "pending") == 0
    finally:
        await engine.dispose()


async def test_claim_next_dir_atomic(tmp_path):
    """Concurrent claims never return the same dir twice."""
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
            repo = DurableScanRepository(session)
            run = await repo.create_scan_run(root_id)
            await repo.add_dirs(
                run.id,
                [(f"/d{i}", 1) for i in range(8)],
            )
            await session.commit()
            run_id = run.id

        async def claim_once() -> IndexScanDir | None:
            async with factory() as session:
                repo = DurableScanRepository(session)
                claimed = await repo.claim_next_dir(run_id)
                await session.commit()
                return claimed

        results = await asyncio.gather(*(claim_once() for _ in range(8)))
        claimed_ids = [c.id for c in results if c is not None]
        assert len(claimed_ids) == 8
        assert len(set(claimed_ids)) == 8

        async with factory() as session:
            repo = DurableScanRepository(session)
            assert await repo.count_dirs(run_id, "running") == 8
            assert await repo.count_dirs(run_id, "pending") == 0
            extra = await repo.claim_next_dir(run_id)
            assert extra is None
    finally:
        await engine.dispose()


async def test_complete_and_fail_dir(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
            repo = DurableScanRepository(session)
            run = await repo.create_scan_run(root_id)
            await repo.add_dirs(run.id, [("/x", 0), ("/y", 0)])
            await session.commit()

            first = await repo.claim_next_dir(run.id)
            second = await repo.claim_next_dir(run.id)
            assert first is not None and second is not None

            await repo.complete_dir(first.id, entry_count=5)
            await repo.fail_dir(second.id, error_message="boom")
            await session.commit()

        async with factory() as session:
            repo = DurableScanRepository(session)
            assert await repo.count_dirs(run.id, "done") == 1
            assert await repo.count_dirs(run.id, "failed") == 1
            done = await session.get(IndexScanDir, first.id)
            failed = await session.get(IndexScanDir, second.id)
            assert done is not None
            assert done.status == "done"
            assert done.entry_count == 5
            assert done.finished_at is not None
            assert failed is not None
            assert failed.status == "failed"
            assert failed.error_message == "boom"
            assert failed.finished_at is not None
    finally:
        await engine.dispose()


async def test_add_and_get_entries(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
            repo = DurableScanRepository(session)
            run = await repo.create_scan_run(root_id)
            await session.commit()

            entries = [
                SnapshotEntry(
                    resource_id=f"res-{i}",
                    path="/docs",
                    name=f"file-{i}",
                    content_hash=f"hash-{i}",
                )
                for i in range(3)
            ]
            await repo.add_entries(run.id, entries)
            await session.commit()

            assert await repo.count_entries(run.id) == 3

        async with factory() as session:
            repo = DurableScanRepository(session)
            fetched = await repo.get_entries(run.id, "/docs")
            assert len(fetched) == 3
            assert {e.resource_id for e in fetched} == {"res-0", "res-1", "res-2"}
            assert all(e.dir_path == "/docs" for e in fetched)
            assert all(e.metadata_hash is not None for e in fetched)

            empty = await repo.get_entries(run.id, "/nonexistent")
            assert empty == []

            await repo.add_entries(run.id, [])
            assert await repo.count_entries(run.id) == 3
    finally:
        await engine.dispose()


async def test_count_dirs_and_entries(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
            repo = DurableScanRepository(session)
            run = await repo.create_scan_run(root_id)
            await repo.add_dirs(run.id, [("/a", 0), ("/b", 1), ("/c", 1)])
            await repo.add_entries(
                run.id,
                [
                    SnapshotEntry(resource_id="r1", path="/a", name="n1"),
                    SnapshotEntry(resource_id="r2", path="/a", name="n2"),
                    SnapshotEntry(resource_id="r3", path="/b", name="n3"),
                ],
            )
            await session.commit()

            assert await repo.count_dirs(run.id) == 3
            assert await repo.count_dirs(run.id, "pending") == 3
            assert await repo.count_dirs(run.id, "done") == 0
            assert await repo.count_entries(run.id) == 3

            claimed = await repo.claim_next_dir(run.id)
            assert claimed is not None
            await session.commit()

        async with factory() as session:
            repo = DurableScanRepository(session)
            assert await repo.count_dirs(run.id, "running") == 1
            assert await repo.count_dirs(run.id, "pending") == 2
            assert await repo.count_dirs(run.id) == 3
            assert await repo.count_entries(run.id) == 3
            assert await repo.count_entries(str(uuid.uuid4())) == 0
    finally:
        await engine.dispose()


async def test_cascade_delete(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
            repo = DurableScanRepository(session)
            run = await repo.create_scan_run(root_id)
            await repo.add_dirs(run.id, [("/a", 0), ("/b", 1)])
            await repo.add_entries(
                run.id,
                [
                    SnapshotEntry(resource_id="r1", path="/a", name="n1"),
                    SnapshotEntry(resource_id="r2", path="/b", name="n2"),
                ],
            )
            await session.commit()
            run_id = run.id

        async with factory() as session:
            repo = DurableScanRepository(session)
            assert await repo.count_dirs(run_id) == 2
            assert await repo.count_entries(run_id) == 2

        async with factory() as session:
            await session.execute(
                text("DELETE FROM index_scan_runs WHERE id = :id"),
                {"id": run_id},
            )
            await session.commit()

        async with factory() as session:
            repo = DurableScanRepository(session)
            assert await repo.get_scan_run(run_id) is None
            assert await repo.count_dirs(run_id) == 0
            assert await repo.count_entries(run_id) == 0
            direct_dirs = (
                await session.execute(
                    text("SELECT COUNT(*) FROM index_scan_dirs")
                )
            ).scalar_one()
            direct_entries = (
                await session.execute(
                    text("SELECT COUNT(*) FROM index_scan_entries")
                )
            ).scalar_one()
            assert direct_dirs == 0
            assert direct_entries == 0
    finally:
        await engine.dispose()
