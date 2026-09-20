"""R2 PR04: durable scan integration tests (V2 doc sections 10, 86).

Exercises the AListProviderAdapter in durable scan mode (feature flag
CLOUDSITE_DURABLE_SCAN_ENABLED=True) to verify checkpoint persistence,
resume after interrupt, stale running recovery, fingerprint rejection,
and feature-flag gating. All tests use temporary SQLite databases with
PRAGMA foreign_keys=ON so FK semantics match production.
"""
from __future__ import annotations

import hashlib
from typing import Any

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from cloudsite.models import IndexScanDir, IndexScanEntry, IndexScanRun
from cloudsite.modules.indexing.domain.snapshot import SnapshotEntry
from cloudsite.modules.indexing.infrastructure.alist_adapter import (
    AListProviderAdapter,
)
from cloudsite.modules.indexing.infrastructure.durable_scan_checkpoint import (
    DirCheckpoint,
    ScanRunManager,
)
from cloudsite.modules.indexing.infrastructure.durable_scan_repository import (
    DurableScanRepository,
)
from cloudsite.modules.providers.contracts.public import ProviderScanRoot
from cloudsite.platform.db import StateBase


# ----------------------------------------------------------------------
# Test infrastructure
# ----------------------------------------------------------------------


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


async def _seed_root_mapping(session: AsyncSession, root_id: int = 1) -> int:
    await session.execute(
        text(
            "INSERT INTO content_root_mappings "
            "(id, connection_id, content_type, display_name, alist_path, enabled, "
            "sort_order, home_order, created_at, updated_at) "
            "VALUES (:id, 1, 'software', :name, :path, 1, 0, 0, "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {"id": root_id, "name": f"root-{root_id}", "path": "/root"},
    )
    await session.commit()
    return root_id


class FakeProvider:
    """ProviderScanPort fake backed by an in-memory directory tree."""

    def __init__(self, tree: dict[str, list[dict[str, Any]]]) -> None:
        self._tree = tree
        self.list_calls: list[str] = []

    async def list_path(
        self,
        path: str,
        refresh: bool = False,
        strict: bool = False,
    ) -> list[dict[str, Any]]:
        self.list_calls.append(path)
        return list(self._tree.get(path, []))

    async def get_metadata(self, path: str) -> dict[str, Any]:
        return {"name": path.rsplit("/", 1)[-1]}


def _make_tree() -> dict[str, list[dict[str, Any]]]:
    """Build:
    /root
      /a (dir)
        /a1 (file)
        /a2 (file)
        /sub (dir)
          /deep.zip (file)
      /b (dir)
        /b1 (file)
      /c (file)
    """
    return {
        "/root": [
            {"name": "a", "is_dir": True},
            {"name": "b", "is_dir": True},
            {"name": "c", "is_dir": False, "size": 100},
        ],
        "/root/a": [
            {"name": "a1", "is_dir": False, "size": 10},
            {"name": "a2", "is_dir": False, "size": 20},
            {"name": "sub", "is_dir": True},
        ],
        "/root/a/sub": [
            {"name": "deep.zip", "is_dir": False, "size": 5},
        ],
        "/root/b": [
            {"name": "b1", "is_dir": False, "size": 30},
        ],
    }


def _make_root(root_mapping_id: int = 1) -> ProviderScanRoot:
    return ProviderScanRoot(
        root_mapping_id=root_mapping_id,
        content_type="software",
        storage_path="/root",
        display_name="Root",
    )


EXPECTED_PATHS = {
    "/root",
    "/root/a",
    "/root/a/a1",
    "/root/a/a2",
    "/root/a/sub",
    "/root/a/sub/deep.zip",
    "/root/b",
    "/root/b/b1",
    "/root/c",
}

EXPECTED_DIRS = {
    "/root",
    "/root/a",
    "/root/a/sub",
    "/root/b",
}


def _fingerprint(root_mapping_id: int, root_path: str, content_type: str) -> str:
    return hashlib.sha256(
        f"{root_mapping_id}:{root_path}:{content_type}".encode()
    ).hexdigest()


def _entry_paths(entries: list) -> set[str]:
    return {e.path for e in entries}


# ----------------------------------------------------------------------
# 1. test_durable_scan_completes
# ----------------------------------------------------------------------


async def test_durable_scan_completes(tmp_path, monkeypatch):
    """Durable scan mode completes normally and marks run completed."""
    monkeypatch.setenv("CLOUDSITE_DURABLE_SCAN_ENABLED", "1")
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            await _seed_root_mapping(session)

        provider = FakeProvider(_make_tree())
        adapter = AListProviderAdapter(provider, [_make_root()])
        async with factory() as session:
            adapter.set_durable_session(session)
            entries, _, complete = await adapter.scan_category("root:1")
            await session.commit()

        assert complete is True
        assert _entry_paths(entries) == EXPECTED_PATHS
        assert len(entries) == len(EXPECTED_PATHS)

        async with factory() as session:
            repo = DurableScanRepository(session)
            runs = await repo.list_scan_runs(1)
            assert len(runs) == 1
            assert runs[0].status == "completed"
    finally:
        await engine.dispose()


# ----------------------------------------------------------------------
# 2. test_durable_scan_results_match_memory
# ----------------------------------------------------------------------


async def test_durable_scan_results_match_memory(tmp_path, monkeypatch):
    """Durable scan produces the same entry set as memory mode."""
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            await _seed_root_mapping(session)

        # Memory mode (flag off)
        monkeypatch.delenv("CLOUDSITE_DURABLE_SCAN_ENABLED", raising=False)
        provider_mem = FakeProvider(_make_tree())
        adapter_mem = AListProviderAdapter(provider_mem, [_make_root()])
        entries_mem, _, complete_mem = await adapter_mem.scan_category("root:1")

        # Durable mode (flag on)
        monkeypatch.setenv("CLOUDSITE_DURABLE_SCAN_ENABLED", "1")
        provider_dur = FakeProvider(_make_tree())
        adapter_dur = AListProviderAdapter(provider_dur, [_make_root()])
        async with factory() as session:
            adapter_dur.set_durable_session(session)
            entries_dur, _, complete_dur = await adapter_dur.scan_category("root:1")
            await session.commit()

        assert complete_mem == complete_dur
        assert _entry_paths(entries_mem) == _entry_paths(entries_dur)
        assert {e.resource_id for e in entries_mem} == {
            e.resource_id for e in entries_dur
        }
        assert len(entries_mem) == len(entries_dur)
    finally:
        await engine.dispose()


# ----------------------------------------------------------------------
# 3. test_durable_scan_checkpoint_persisted
# ----------------------------------------------------------------------


async def test_durable_scan_checkpoint_persisted(tmp_path, monkeypatch):
    """Checkpoint data is persisted to index_scan_entries and index_scan_dirs."""
    monkeypatch.setenv("CLOUDSITE_DURABLE_SCAN_ENABLED", "1")
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            await _seed_root_mapping(session)

        provider = FakeProvider(_make_tree())
        adapter = AListProviderAdapter(provider, [_make_root()])
        async with factory() as session:
            adapter.set_durable_session(session)
            await adapter.scan_category("root:1")
            await session.commit()

        async with factory() as session:
            repo = DurableScanRepository(session)
            runs = await repo.list_scan_runs(1)
            run_id = runs[0].id

            entry_count = await repo.count_entries(run_id)
            assert entry_count > 0

            done_count = await repo.count_dirs(run_id, "done")
            assert done_count == len(EXPECTED_DIRS)

            pending_count = await repo.count_dirs(run_id, "pending")
            assert pending_count == 0

            assert runs[0].status == "completed"
    finally:
        await engine.dispose()


# ----------------------------------------------------------------------
# 4. test_durable_scan_resume_after_interrupt
# ----------------------------------------------------------------------


async def test_durable_scan_resume_after_interrupt(tmp_path, monkeypatch):
    """Simulate interrupt (some dirs done, some pending) -> resume -> complete."""
    monkeypatch.setenv("CLOUDSITE_DURABLE_SCAN_ENABLED", "1")
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)

        fp = _fingerprint(root_id, "/root", "software")

        # Phase 1: manually start a run and checkpoint the root dir as done
        # with its child dirs as pending (simulating interrupt after root scan)
        async with factory() as session:
            mgr = ScanRunManager(session)
            run = await mgr.start_scan(root_id, fingerprint=fp)
            run_id = run.id
            repo = DurableScanRepository(session)
            ckpt = DirCheckpoint(session)

            await repo.add_dirs(run_id, [("/root", 0)])
            claimed = await repo.claim_next_dir(run_id)
            assert claimed is not None

            root_entries = [
                SnapshotEntry(resource_id="r_a", path="/root/a", name="a"),
                SnapshotEntry(resource_id="r_b", path="/root/b", name="b"),
                SnapshotEntry(resource_id="r_c", path="/root/c", name="c"),
            ]
            child_dirs = [("/root/a", 1), ("/root/b", 1)]
            await ckpt.checkpoint_dir(
                run_id, "/root", root_entries, child_dirs
            )
            await session.commit()

        # Phase 2: resume via scan_category — should skip /root, scan children
        provider = FakeProvider(_make_tree())
        adapter = AListProviderAdapter(provider, [_make_root()])
        async with factory() as session:
            adapter.set_durable_session(session)
            entries, _, complete = await adapter.scan_category("root:1")
            await session.commit()

        assert complete is True
        assert _entry_paths(entries) == EXPECTED_PATHS

        # /root should NOT have been re-listed (it was done)
        assert "/root" not in provider.list_calls
        # child dirs should have been listed
        assert "/root/a" in provider.list_calls
        assert "/root/b" in provider.list_calls

        async with factory() as session:
            repo = DurableScanRepository(session)
            assert await repo.count_dirs(run_id, "done") == len(EXPECTED_DIRS)
            assert await repo.count_dirs(run_id, "pending") == 0
    finally:
        await engine.dispose()


# ----------------------------------------------------------------------
# 5. test_durable_scan_done_dirs_not_rescanned
# ----------------------------------------------------------------------


async def test_durable_scan_done_dirs_not_rescanned(tmp_path, monkeypatch):
    """Done directories are not re-listed on resume."""
    monkeypatch.setenv("CLOUDSITE_DURABLE_SCAN_ENABLED", "1")
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)

        fp = _fingerprint(root_id, "/root", "software")

        # Set up: root and /root/a are done, /root/b and /root/a/sub are pending
        async with factory() as session:
            mgr = ScanRunManager(session)
            run = await mgr.start_scan(root_id, fingerprint=fp)
            run_id = run.id
            repo = DurableScanRepository(session)
            ckpt = DirCheckpoint(session)

            # Root dir done with children
            await repo.add_dirs(run_id, [("/root", 0)])
            await repo.claim_next_dir(run_id)
            await ckpt.checkpoint_dir(
                run_id,
                "/root",
                [
                    SnapshotEntry(resource_id="r_a", path="/root/a", name="a"),
                    SnapshotEntry(resource_id="r_b", path="/root/b", name="b"),
                    SnapshotEntry(resource_id="r_c", path="/root/c", name="c"),
                ],
                [("/root/a", 1), ("/root/b", 1)],
            )

            # Claim one child dir (whichever UUID order gives us) and checkpoint
            # it as done with its children. We checkpoint /root/a specifically
            # by looking it up by path.
            await repo.claim_next_dir(run_id)  # claim one child
            await repo.claim_next_dir(run_id)  # claim the other child
            # Mark /root/a as done with /root/a/sub as pending
            await ckpt.checkpoint_dir(
                run_id,
                "/root/a",
                [
                    SnapshotEntry(resource_id="r_a1", path="/root/a/a1", name="a1"),
                    SnapshotEntry(resource_id="r_a2", path="/root/a/a2", name="a2"),
                    SnapshotEntry(resource_id="r_sub", path="/root/a/sub", name="sub"),
                ],
                [("/root/a/sub", 2)],
            )
            await session.commit()

        # Resume: should scan /root/b and /root/a/sub, NOT /root or /root/a
        provider = FakeProvider(_make_tree())
        adapter = AListProviderAdapter(provider, [_make_root()])
        async with factory() as session:
            adapter.set_durable_session(session)
            entries, _, complete = await adapter.scan_category("root:1")
            await session.commit()

        assert complete is True
        assert "/root" not in provider.list_calls
        assert "/root/a" not in provider.list_calls
        assert "/root/b" in provider.list_calls
        assert "/root/a/sub" in provider.list_calls
    finally:
        await engine.dispose()


# ----------------------------------------------------------------------
# 6. test_durable_scan_stale_running_recovered
# ----------------------------------------------------------------------


async def test_durable_scan_stale_running_recovered(tmp_path, monkeypatch):
    """Stale running dirs are recovered to pending and scan completes."""
    monkeypatch.setenv("CLOUDSITE_DURABLE_SCAN_ENABLED", "1")
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)

        fp = _fingerprint(root_id, "/root", "software")

        # Set up: root done, /root/a and /root/b left in "running" (stale)
        async with factory() as session:
            mgr = ScanRunManager(session)
            run = await mgr.start_scan(root_id, fingerprint=fp)
            run_id = run.id
            repo = DurableScanRepository(session)
            ckpt = DirCheckpoint(session)

            await repo.add_dirs(run_id, [("/root", 0)])
            await repo.claim_next_dir(run_id)
            await ckpt.checkpoint_dir(
                run_id,
                "/root",
                [
                    SnapshotEntry(resource_id="r_a", path="/root/a", name="a"),
                    SnapshotEntry(resource_id="r_b", path="/root/b", name="b"),
                    SnapshotEntry(resource_id="r_c", path="/root/c", name="c"),
                ],
                [("/root/a", 1), ("/root/b", 1)],
            )

            # Claim both child dirs (they become "running") — simulate crash
            await repo.claim_next_dir(run_id)
            await repo.claim_next_dir(run_id)
            await session.commit()

        # Verify stale running state
        async with factory() as session:
            repo = DurableScanRepository(session)
            assert await repo.count_dirs(run_id, "running") == 2

        # Resume: stale running dirs should be recovered to pending
        provider = FakeProvider(_make_tree())
        adapter = AListProviderAdapter(provider, [_make_root()])
        async with factory() as session:
            adapter.set_durable_session(session)
            entries, _, complete = await adapter.scan_category("root:1")
            await session.commit()

        assert complete is True
        assert _entry_paths(entries) == EXPECTED_PATHS

        async with factory() as session:
            repo = DurableScanRepository(session)
            assert await repo.count_dirs(run_id, "running") == 0
            assert await repo.count_dirs(run_id, "done") == len(EXPECTED_DIRS)
    finally:
        await engine.dispose()


# ----------------------------------------------------------------------
# 7. test_durable_scan_fingerprint_rejected
# ----------------------------------------------------------------------


async def test_durable_scan_fingerprint_rejected(tmp_path, monkeypatch):
    """Fingerprint mismatch causes a fresh scan instead of resume."""
    monkeypatch.setenv("CLOUDSITE_DURABLE_SCAN_ENABLED", "1")
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)

        # Set up a run with a DIFFERENT fingerprint
        async with factory() as session:
            mgr = ScanRunManager(session)
            run = await mgr.start_scan(root_id, fingerprint="stale-fp")
            stale_run_id = run.id
            repo = DurableScanRepository(session)
            await repo.add_dirs(stale_run_id, [("/root", 0)])
            await session.commit()

        # Scan with the correct fingerprint — should NOT resume, should start new
        provider = FakeProvider(_make_tree())
        adapter = AListProviderAdapter(provider, [_make_root()])
        async with factory() as session:
            adapter.set_durable_session(session)
            entries, _, complete = await adapter.scan_category("root:1")
            await session.commit()

        assert complete is True
        assert _entry_paths(entries) == EXPECTED_PATHS

        async with factory() as session:
            repo = DurableScanRepository(session)
            runs = await repo.list_scan_runs(1)
            assert len(runs) == 2
            statuses = {r.status for r in runs}
            assert "completed" in statuses
            # The stale-fp run should still be running (not resumed)
            stale_run = await repo.get_scan_run(stale_run_id)
            assert stale_run.status == "running"
    finally:
        await engine.dispose()


# ----------------------------------------------------------------------
# 8. test_durable_scan_feature_flag_off
# ----------------------------------------------------------------------


async def test_durable_scan_feature_flag_off(tmp_path, monkeypatch):
    """Flag=False -> memory mode, no scan_run rows created."""
    monkeypatch.delenv("CLOUDSITE_DURABLE_SCAN_ENABLED", raising=False)
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            await _seed_root_mapping(session)

        provider = FakeProvider(_make_tree())
        adapter = AListProviderAdapter(provider, [_make_root()])
        async with factory() as session:
            adapter.set_durable_session(session)
            entries, _, complete = await adapter.scan_category("root:1")
            await session.commit()

        assert complete is True
        assert _entry_paths(entries) == EXPECTED_PATHS

        async with factory() as session:
            repo = DurableScanRepository(session)
            runs = await repo.list_scan_runs(1)
            assert len(runs) == 0
    finally:
        await engine.dispose()


# ----------------------------------------------------------------------
# 9. test_durable_scan_feature_flag_on
# ----------------------------------------------------------------------


async def test_durable_scan_feature_flag_on(tmp_path, monkeypatch):
    """Flag=True -> durable mode, scan_run row created and completed."""
    monkeypatch.setenv("CLOUDSITE_DURABLE_SCAN_ENABLED", "1")
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            await _seed_root_mapping(session)

        provider = FakeProvider(_make_tree())
        adapter = AListProviderAdapter(provider, [_make_root()])
        async with factory() as session:
            adapter.set_durable_session(session)
            entries, _, complete = await adapter.scan_category("root:1")
            await session.commit()

        assert complete is True
        assert _entry_paths(entries) == EXPECTED_PATHS

        async with factory() as session:
            repo = DurableScanRepository(session)
            runs = await repo.list_scan_runs(1)
            assert len(runs) == 1
            assert runs[0].status == "completed"
            assert runs[0].fingerprint is not None
    finally:
        await engine.dispose()
