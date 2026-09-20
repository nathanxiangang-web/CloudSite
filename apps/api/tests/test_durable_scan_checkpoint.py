"""R2 PR03: durable scan checkpoint logic tests (V2 doc sections 14-18).

Exercises ScanRunManager and DirCheckpoint over the durable scan-progress
tables. All tests use temporary SQLite databases with PRAGMA
foreign_keys=ON so cascade-delete and FK semantics match production.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from cloudsite.models import IndexScanDir
from cloudsite.modules.indexing.domain.snapshot import SnapshotEntry
from cloudsite.modules.indexing.infrastructure.durable_scan_checkpoint import (
    DirCheckpoint,
    RESUME_MAX_AGE,
    ResumeResult,
    ScanRunManager,
)
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
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
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


async def _start_run(factory, root_id: int, fingerprint: str = "fp-1"):
    async with factory() as session:
        mgr = ScanRunManager(session)
        run = await mgr.start_scan(root_id, fingerprint=fingerprint)
        await session.commit()
        return run.id


# ----------------------------------------------------------------------
# ScanRunManager lifecycle
# ----------------------------------------------------------------------


async def test_scan_run_lifecycle(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
            mgr = ScanRunManager(session)
            run = await mgr.start_scan(root_id, fingerprint="fp-1")
            assert run.status == "running"
            assert run.fingerprint == "fp-1"
            await session.commit()
            run_id = run.id

        async with factory() as session:
            mgr = ScanRunManager(session)
            await mgr.complete_scan(run_id)
            await session.commit()

        async with factory() as session:
            mgr = ScanRunManager(session)
            run = await mgr._repo.get_scan_run(run_id)
            assert run.status == "completed"
            assert run.finished_at is not None

        async with factory() as session:
            root_id2 = await _seed_root_mapping(session, root_id=1002)
            mgr = ScanRunManager(session)
            run2 = await mgr.start_scan(root_id2)
            await mgr.fail_scan(run2.id, "boom")
            await session.commit()
            failed = await mgr._repo.get_scan_run(run2.id)
            assert failed.status == "failed"
            assert failed.error_message == "boom"

        async with factory() as session:
            root_id3 = await _seed_root_mapping(session, root_id=1003)
            mgr = ScanRunManager(session)
            run3 = await mgr.start_scan(root_id3)
            await mgr.cancel_scan(run3.id)
            await session.commit()
            cancelled = await mgr._repo.get_scan_run(run3.id)
            assert cancelled.status == "cancelled"
    finally:
        await engine.dispose()


async def test_expire_stale_runs(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
            mgr = ScanRunManager(session)
            fresh = await mgr.start_scan(root_id, fingerprint="fresh")
            stale = await mgr.start_scan(root_id, fingerprint="stale")
            await session.commit()
            # backdate the stale run started_at to 2 hours ago
            old = datetime.now(timezone.utc) - timedelta(hours=2)
            await session.execute(
                text(
                    "UPDATE index_scan_runs SET started_at = :old WHERE id = :id"
                ),
                {"old": old, "id": stale.id},
            )
            await session.commit()

        async with factory() as session:
            mgr = ScanRunManager(session)
            count = await mgr.expire_stale_runs(max_age=timedelta(minutes=60))
            await session.commit()
            assert count == 1

        async with factory() as session:
            mgr = ScanRunManager(session)
            stale_run = await mgr._repo.get_scan_run(stale.id)
            fresh_run = await mgr._repo.get_scan_run(fresh.id)
            assert stale_run.status == "expired"
            assert stale_run.finished_at is not None
            assert fresh_run.status == "running"
    finally:
        await engine.dispose()


# ----------------------------------------------------------------------
# Checkpoint transaction
# ----------------------------------------------------------------------


async def test_checkpoint_dir_atomic(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
            run_id = await _start_run(factory, root_id)
        # re-open to add+claim the dir
        async with factory() as session:
            repo = DurableScanRepository(session)
            await repo.add_dirs(run_id, [("/parent", 0)])
            claimed = await repo.claim_next_dir(run_id)
            assert claimed is not None
            await session.commit()

        entries = [
            SnapshotEntry(resource_id="r1", path="/parent", name="f1"),
            SnapshotEntry(resource_id="r2", path="/parent", name="f2"),
        ]
        child_dirs = [("/parent/a", 1), ("/parent/b", 1)]

        async with factory() as session:
            ckpt = DirCheckpoint(session)
            await ckpt.checkpoint_dir(run_id, "/parent", entries, child_dirs)
            await session.commit()

        # all three changes committed together in one transaction
        async with factory() as session:
            repo = DurableScanRepository(session)
            assert await repo.count_entries(run_id) == 2
            assert await repo.count_dirs(run_id, "pending") == 2
            assert await repo.count_dirs(run_id, "done") == 1
            fetched_entries = await repo.get_entries(run_id, "/parent")
            assert {e.resource_id for e in fetched_entries} == {"r1", "r2"}
            child_paths = {
                d.path
                for d in (
                    await session.execute(
                        text(
                            "SELECT path FROM index_scan_dirs "
                            "WHERE scan_run_id = :r AND status = 'pending'"
                        ),
                        {"r": run_id},
                    )
                ).all()
            }
            assert child_paths == {"/parent/a", "/parent/b"}
    finally:
        await engine.dispose()


async def test_children_saved_before_dir_done(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
            run_id = await _start_run(factory, root_id)
        async with factory() as session:
            repo = DurableScanRepository(session)
            await repo.add_dirs(run_id, [("/parent", 0)])
            await repo.claim_next_dir(run_id)
            await session.commit()

        async with factory() as session:
            ckpt = DirCheckpoint(session)
            call_order: list[str] = []
            orig_complete = ckpt._repo.complete_dir
            orig_add_dirs = ckpt._repo.add_dirs
            orig_add_entries = ckpt._repo.add_entries

            async def spy_add_entries(run_id_, entries_):
                call_order.append("add_entries")
                await orig_add_entries(run_id_, entries_)

            async def spy_add_dirs(run_id_, dirs_):
                call_order.append("add_dirs")
                await orig_add_dirs(run_id_, dirs_)

            async def spy_complete(dir_id, entry_count):
                # at this moment children + entries must already be flushed
                pending = await ckpt._repo.count_dirs(run_id, "pending")
                ents = await ckpt._repo.count_entries(run_id)
                assert pending >= 2, "children must be saved before dir done"
                assert ents >= 1, "entries must be saved before dir done"
                call_order.append("complete_dir")
                await orig_complete(dir_id, entry_count)

            ckpt._repo.add_entries = spy_add_entries
            ckpt._repo.add_dirs = spy_add_dirs
            ckpt._repo.complete_dir = spy_complete

            entries = [SnapshotEntry(resource_id="r1", path="/parent", name="f1")]
            await ckpt.checkpoint_dir(
                run_id, "/parent", entries, [("/parent/a", 1), ("/parent/b", 1)]
            )
            await session.commit()

            assert call_order.index("add_entries") < call_order.index("complete_dir")
            assert call_order.index("add_dirs") < call_order.index("complete_dir")
    finally:
        await engine.dispose()


async def test_checkpoint_idempotent(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
            run_id = await _start_run(factory, root_id)
        async with factory() as session:
            repo = DurableScanRepository(session)
            await repo.add_dirs(run_id, [("/parent", 0)])
            await repo.claim_next_dir(run_id)
            await session.commit()

        entries = [SnapshotEntry(resource_id="r1", path="/parent", name="f1")]
        child_dirs = [("/parent/a", 1)]

        async with factory() as session:
            ckpt = DirCheckpoint(session)
            await ckpt.checkpoint_dir(run_id, "/parent", entries, child_dirs)
            # second call must not raise
            await ckpt.checkpoint_dir(run_id, "/parent", entries, child_dirs)
            await session.commit()

        async with factory() as session:
            repo = DurableScanRepository(session)
            assert await repo.count_dirs(run_id, "done") == 1
            assert await repo.count_dirs(run_id, "pending") == 1
            assert await repo.count_entries(run_id) == 1
    finally:
        await engine.dispose()


# ----------------------------------------------------------------------
# Crash recovery
# ----------------------------------------------------------------------


async def test_recover_interrupted_running_to_pending(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
            run_id = await _start_run(factory, root_id)
        async with factory() as session:
            repo = DurableScanRepository(session)
            await repo.add_dirs(run_id, [("/a", 0), ("/b", 0), ("/c", 0)])
            await repo.claim_next_dir(run_id)  # /a -> running
            await repo.claim_next_dir(run_id)  # /b -> running
            await session.commit()

        async with factory() as session:
            ckpt = DirCheckpoint(session)
            await ckpt.recover_interrupted(run_id)
            await session.commit()

        async with factory() as session:
            repo = DurableScanRepository(session)
            assert await repo.count_dirs(run_id, "running") == 0
            assert await repo.count_dirs(run_id, "pending") == 3
    finally:
        await engine.dispose()


async def test_recover_done_not_affected(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
            run_id = await _start_run(factory, root_id)
        async with factory() as session:
            repo = DurableScanRepository(session)
            await repo.add_dirs(run_id, [("/a", 0), ("/b", 0)])
            claimed = await repo.claim_next_dir(run_id)
            await repo.complete_dir(claimed.id, entry_count=0)
            await repo.claim_next_dir(run_id)  # /b -> running
            await session.commit()

        async with factory() as session:
            ckpt = DirCheckpoint(session)
            await ckpt.recover_interrupted(run_id)
            await session.commit()

        async with factory() as session:
            repo = DurableScanRepository(session)
            assert await repo.count_dirs(run_id, "done") == 1
            assert await repo.count_dirs(run_id, "running") == 0
            assert await repo.count_dirs(run_id, "pending") == 1
    finally:
        await engine.dispose()


async def test_recover_then_resume_only_pending(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
            run_id = await _start_run(factory, root_id, fingerprint="fp-1")
        all_paths = {"/a", "/b", "/c"}
        done_path = ""
        async with factory() as session:
            repo = DurableScanRepository(session)
            await repo.add_dirs(run_id, [("/a", 0), ("/b", 0), ("/c", 0)])
            await session.commit()
            # claim one and complete it (done)
            done_dir = await repo.claim_next_dir(run_id)
            await repo.complete_dir(done_dir.id, entry_count=0)
            # claim another and leave it running (stale)
            await repo.claim_next_dir(run_id)
            await session.commit()
            done_path = done_dir.path
            remaining = all_paths - {done_path}

        async with factory() as session:
            ckpt = DirCheckpoint(session)
            await ckpt.recover_interrupted(run_id)
            await session.commit()

        async with factory() as session:
            ckpt = DirCheckpoint(session)
            result = await ckpt.resume_scan(run_id, "fp-1")
            assert result.resumed is True
            paths = {d.path for d in result.pending_dirs}
            # done dir excluded; stale recovered to pending; never-claimed pending
            assert paths == remaining
            assert done_path not in paths
            assert all(d.status == "pending" for d in result.pending_dirs)
    finally:
        await engine.dispose()


# ----------------------------------------------------------------------
# Resume
# ----------------------------------------------------------------------


async def test_resume_valid_fingerprint(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
            run_id = await _start_run(factory, root_id, fingerprint="fp-1")
        async with factory() as session:
            repo = DurableScanRepository(session)
            await repo.add_dirs(run_id, [("/a", 0), ("/b", 0)])
            await session.commit()

        async with factory() as session:
            ckpt = DirCheckpoint(session)
            result = await ckpt.resume_scan(run_id, "fp-1")
            assert result.resumed is True
            assert result.reason is None
            assert len(result.pending_dirs) == 2
    finally:
        await engine.dispose()


async def test_resume_invalid_fingerprint_rejected(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
            run_id = await _start_run(factory, root_id, fingerprint="fp-1")
        async with factory() as session:
            ckpt = DirCheckpoint(session)
            result = await ckpt.resume_scan(run_id, "fp-different")
            assert result.resumed is False
            assert result.reason == "fingerprint_mismatch"
            assert result.pending_dirs == []
    finally:
        await engine.dispose()


async def test_resume_expired_run(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
            run_id = await _start_run(factory, root_id, fingerprint="fp-1")
        async with factory() as session:
            mgr = ScanRunManager(session)
            await mgr._repo.update_scan_run_status(run_id, "expired")
            await session.commit()

        async with factory() as session:
            ckpt = DirCheckpoint(session)
            result = await ckpt.resume_scan(run_id, "fp-1")
            assert result.resumed is False
            assert result.reason == "run_expired"
            assert result.pending_dirs == []
    finally:
        await engine.dispose()


async def test_resume_max_age_60min(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
            run_id = await _start_run(factory, root_id, fingerprint="fp-1")
        # backdate to 30 minutes ago (within 60 min window)
        async with factory() as session:
            recent = datetime.now(timezone.utc) - timedelta(minutes=30)
            await session.execute(
                text(
                    "UPDATE index_scan_runs SET started_at = :old WHERE id = :id"
                ),
                {"old": recent, "id": run_id},
            )
            await session.commit()

        async with factory() as session:
            repo = DurableScanRepository(session)
            await repo.add_dirs(run_id, [("/a", 0)])
            await session.commit()

        async with factory() as session:
            ckpt = DirCheckpoint(session)
            result = await ckpt.resume_scan(run_id, "fp-1")
            assert result.resumed is True
            assert len(result.pending_dirs) == 1

        # now backdate beyond 60 min and confirm it is expired + refused
        async with factory() as session:
            too_old = datetime.now(timezone.utc) - timedelta(minutes=70)
            await session.execute(
                text(
                    "UPDATE index_scan_runs SET started_at = :old, status='running' "
                    "WHERE id = :id"
                ),
                {"old": too_old, "id": run_id},
            )
            await session.commit()

        async with factory() as session:
            ckpt = DirCheckpoint(session)
            result = await ckpt.resume_scan(run_id, "fp-1")
            assert result.resumed is False
            assert result.reason == "run_expired_max_age"
            await session.commit()

        async with factory() as session:
            mgr = ScanRunManager(session)
            run = await mgr._repo.get_scan_run(run_id)
            assert run.status == "expired"
    finally:
        await engine.dispose()


# ----------------------------------------------------------------------
# Complete Gate
# ----------------------------------------------------------------------


async def _seed_run_with_dirs(factory, root_id, statuses):
    """Create a run and set its dirs to the given statuses."""
    async with factory() as session:
        mgr = ScanRunManager(session)
        run = await mgr.start_scan(root_id, fingerprint="fp-1")
        await session.commit()
        run_id = run.id
    async with factory() as session:
        repo = DurableScanRepository(session)
        paths = [f"/d{i}" for i in range(len(statuses))]
        await repo.add_dirs(run_id, [(p, 0) for p in paths])
        await session.commit()
        # claim each then set status
        for path, status in zip(paths, statuses):
            if status == "pending":
                continue
            claimed = await repo.claim_next_dir(run_id)
            assert claimed is not None
            if status == "running":
                continue
            if status == "done":
                await repo.complete_dir(claimed.id, entry_count=0)
            elif status == "failed":
                await repo.fail_dir(claimed.id, "err")
        await session.commit()
    return run_id


async def test_complete_gate_all_done(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
        run_id = await _seed_run_with_dirs(factory, root_id, ["done", "done"])
        async with factory() as session:
            ckpt = DirCheckpoint(session)
            result = await ckpt.is_scan_complete(run_id)
            assert result.complete is True
            assert result.reason is None
            assert result.suppressed_count == 0
    finally:
        await engine.dispose()


async def test_complete_gate_has_pending(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
        run_id = await _seed_run_with_dirs(
            factory, root_id, ["done", "pending"]
        )
        async with factory() as session:
            ckpt = DirCheckpoint(session)
            result = await ckpt.is_scan_complete(run_id)
            assert result.complete is False
            assert result.reason == "pending_dirs"
            assert result.suppressed_count == 1
    finally:
        await engine.dispose()


async def test_complete_gate_has_failed(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
        run_id = await _seed_run_with_dirs(
            factory, root_id, ["done", "failed"]
        )
        async with factory() as session:
            ckpt = DirCheckpoint(session)
            result = await ckpt.is_scan_complete(run_id)
            assert result.complete is False
            assert result.reason == "failed_dirs"
            assert result.suppressed_count == 1
    finally:
        await engine.dispose()


async def test_complete_gate_has_running(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
        run_id = await _seed_run_with_dirs(
            factory, root_id, ["done", "running"]
        )
        async with factory() as session:
            ckpt = DirCheckpoint(session)
            result = await ckpt.is_scan_complete(run_id)
            assert result.complete is False
            assert result.reason == "running_dirs"
            assert result.suppressed_count == 1
    finally:
        await engine.dispose()
