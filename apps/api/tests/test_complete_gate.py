"""R3 PR01: Complete Gate tests (V2 doc sections 18-19).

The Complete Gate is the deletion safety door: only a fully complete
snapshot (every dir done AND pagination complete) is allowed to drive
removal reconcile. When the gate fails, additions/changes are still
applied but removals are suppressed, the run is marked degraded, and a
WARNING is logged.

Tests 1-5 exercise DirCheckpoint.is_scan_complete (the infrastructure
gate evaluator) over the durable scan-progress tables. Tests 6-10
exercise ReconcileService.reconcile with a ScanRunSummary to verify the
application-level gate behavior (additions allowed, removals suppressed,
degraded flag, suppressed count, WARNING log).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from cloudsite.modules.indexing.application.reconcile import (
    ReconcileService,
    ScanRunSummary,
)
from cloudsite.modules.indexing.domain.snapshot import CategorySnapshot, SnapshotEntry
from cloudsite.modules.indexing.infrastructure.durable_scan_checkpoint import (
    CompleteGateResult,
    DirCheckpoint,
    ScanRunManager,
)
from cloudsite.modules.indexing.infrastructure.durable_scan_repository import (
    DurableScanRepository,
)
from cloudsite.modules.indexing.infrastructure.repository import IndexedEntry
from cloudsite.platform.db import StateBase


# ----------------------------------------------------------------------
# Infrastructure helpers (mirror test_durable_scan_checkpoint.py)
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


async def _seed_root_mapping(session: AsyncSession, root_id: int = 2001) -> int:
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


# ----------------------------------------------------------------------
# Reconcile helpers (mirror test_reconcile.py)
# ----------------------------------------------------------------------


class _FakeIndexingStore:
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
        path=f'/{rid}', name=rid, content_hash=content_hash,
    )


def _snap_for(rid: str, content_hash: str | None = 'h1') -> SnapshotEntry:
    """Snapshot entry whose path matches the _indexed helper for the same rid."""
    return SnapshotEntry(resource_id=rid, path=f'/{rid}', name=rid, content_hash=content_hash)


# ======================================================================
# 1-5. Complete Gate evaluation (DirCheckpoint.is_scan_complete)
# ======================================================================


async def test_complete_gate_all_done(tmp_path):
    """All dirs done + pagination_complete=True -> gate complete, removal allowed."""
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
        run_id = await _seed_run_with_dirs(factory, root_id, ["done", "done"])
        async with factory() as session:
            ckpt = DirCheckpoint(session)
            result = await ckpt.is_scan_complete(run_id, pagination_complete=True)
            assert isinstance(result, CompleteGateResult)
            assert result.complete is True
            assert result.reason is None
            assert result.suppressed_count == 0
    finally:
        await engine.dispose()


async def test_complete_gate_has_pending(tmp_path):
    """Has pending dirs -> gate not complete, removal blocked."""
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
        run_id = await _seed_run_with_dirs(factory, root_id, ["done", "pending"])
        async with factory() as session:
            ckpt = DirCheckpoint(session)
            result = await ckpt.is_scan_complete(run_id, pagination_complete=True)
            assert result.complete is False
            assert result.reason == "pending_dirs"
            assert result.suppressed_count == 1
    finally:
        await engine.dispose()


async def test_complete_gate_has_running(tmp_path):
    """Has running dirs -> gate not complete, removal blocked."""
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
        run_id = await _seed_run_with_dirs(factory, root_id, ["done", "running"])
        async with factory() as session:
            ckpt = DirCheckpoint(session)
            result = await ckpt.is_scan_complete(run_id, pagination_complete=True)
            assert result.complete is False
            assert result.reason == "running_dirs"
            assert result.suppressed_count == 1
    finally:
        await engine.dispose()


async def test_complete_gate_has_failed(tmp_path):
    """Has failed dirs -> gate not complete, removal blocked."""
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
        run_id = await _seed_run_with_dirs(factory, root_id, ["done", "failed"])
        async with factory() as session:
            ckpt = DirCheckpoint(session)
            result = await ckpt.is_scan_complete(run_id, pagination_complete=True)
            assert result.complete is False
            assert result.reason == "failed_dirs"
            assert result.suppressed_count == 1
    finally:
        await engine.dispose()


async def test_complete_gate_pagination_incomplete(tmp_path):
    """All dirs done but pagination_complete=False -> gate not complete."""
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
        run_id = await _seed_run_with_dirs(factory, root_id, ["done", "done"])
        async with factory() as session:
            ckpt = DirCheckpoint(session)
            result = await ckpt.is_scan_complete(run_id, pagination_complete=False)
            assert result.complete is False
            assert result.reason == "pagination_incomplete"
            assert result.suppressed_count == 0
    finally:
        await engine.dispose()


# ======================================================================
# 6-10. Reconcile behavior under the Complete Gate
# ======================================================================


async def test_incomplete_snapshot_additions_allowed():
    """Gate incomplete but additions/changes are still applied."""
    existing = [_indexed('keep', content_hash='h1')]
    store = _FakeIndexingStore(existing=existing)
    service = ReconcileService(store)

    snapshot = CategorySnapshot(
        category_id='cat', provider_id='prov',
        entries=[
            _snap_for('keep', content_hash='h2'),
            _snap_for('new'),
        ],
        pagination_complete=True,
    )
    scan_run = ScanRunSummary(
        pending_dirs=1, running_dirs=0, failed_dirs=0,
        pagination_complete=True,
    )
    result = await service.reconcile(snapshot, scan_run=scan_run)

    assert result.writes.added == 1
    assert result.writes.changed == 1
    assert len(store.upsert_calls) == 1
    assert store.remove_calls == []


async def test_incomplete_snapshot_removals_suppressed():
    """Gate incomplete -> removals suppressed, no remove() calls."""
    existing = [_indexed('old1'), _indexed('old2'), _indexed('old3')]
    store = _FakeIndexingStore(existing=existing)
    service = ReconcileService(store)

    snapshot = CategorySnapshot(
        category_id='cat', provider_id='prov',
        entries=[_snap_for('old1')],
        pagination_complete=True,
    )
    scan_run = ScanRunSummary(
        pending_dirs=0, running_dirs=1, failed_dirs=0,
        pagination_complete=True,
    )
    result = await service.reconcile(snapshot, scan_run=scan_run)

    assert store.remove_calls == []
    assert result.writes.removed == 0
    assert result.suppressed_removals == 2


async def test_degraded_run_marked():
    """Gate incomplete -> result.degraded is True and reason is recorded."""
    existing = [_indexed('old1'), _indexed('old2')]
    store = _FakeIndexingStore(existing=existing)
    service = ReconcileService(store)

    snapshot = CategorySnapshot(
        category_id='cat', provider_id='prov',
        entries=[_snap_for('old1')],
        pagination_complete=True,
    )
    scan_run = ScanRunSummary(
        pending_dirs=0, running_dirs=0, failed_dirs=1,
        pagination_complete=True,
    )
    result = await service.reconcile(snapshot, scan_run=scan_run)

    assert result.degraded is True
    assert result.complete_gate_reason == "failed_dirs"


async def test_suppressed_removals_counted():
    """suppressed_removals == len(existing) - len(staging intersection)."""
    existing = [_indexed('a'), _indexed('b'), _indexed('c'), _indexed('d')]
    store = _FakeIndexingStore(existing=existing)
    service = ReconcileService(store)

    snapshot = CategorySnapshot(
        category_id='cat', provider_id='prov',
        entries=[_snap_for('a'), _snap_for('b')],
        pagination_complete=True,
    )
    scan_run = ScanRunSummary(
        pending_dirs=0, running_dirs=0, failed_dirs=0,
        pagination_complete=False,
    )
    result = await service.reconcile(snapshot, scan_run=scan_run)

    assert result.suppressed_removals == 2
    assert result.writes.removed == 0
    assert result.degraded is True
    assert result.complete_gate_reason == "pagination_incomplete"


async def test_complete_gate_logs_warning(caplog):
    """Gate incomplete with removals -> WARNING logged with reason and count."""
    existing = [_indexed('old1'), _indexed('old2'), _indexed('old3')]
    store = _FakeIndexingStore(existing=existing)
    service = ReconcileService(store)

    snapshot = CategorySnapshot(
        category_id='cat', provider_id='prov',
        entries=[_snap_for('old1')],
        pagination_complete=True,
    )
    scan_run = ScanRunSummary(
        pending_dirs=2, running_dirs=0, failed_dirs=0,
        pagination_complete=True,
    )
    with caplog.at_level(logging.WARNING, logger="cloudsite.modules.indexing.application.reconcile"):
        result = await service.reconcile(snapshot, scan_run=scan_run)

    assert result.degraded is True
    assert result.suppressed_removals == 2
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) >= 1
    msg = warnings[0].getMessage()
    assert "complete gate failed" in msg
    assert "pending_dirs" in msg
    assert "degraded" in msg


# ----------------------------------------------------------------------
# Bonus: gate-passed path still performs removal (regression guard)
# ----------------------------------------------------------------------


async def test_complete_gate_pass_allows_removal():
    """Gate fully complete -> removals proceed normally (not suppressed)."""
    existing = [_indexed('old1'), _indexed('old2')]
    store = _FakeIndexingStore(existing=existing)
    service = ReconcileService(store)

    snapshot = CategorySnapshot(
        category_id='cat', provider_id='prov',
        entries=[_snap_for('old1')],
        pagination_complete=True,
    )
    scan_run = ScanRunSummary(
        pending_dirs=0, running_dirs=0, failed_dirs=0,
        pagination_complete=True,
    )
    result = await service.reconcile(snapshot, scan_run=scan_run)

    assert result.degraded is False
    assert result.complete_gate_reason is None
    assert result.writes.removed == 1
    assert result.suppressed_removals == 0
    assert len(store.remove_calls) == 1
