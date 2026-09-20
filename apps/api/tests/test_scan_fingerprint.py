"""R5 PR03: ScanFingerprint generation and invalidation tests (V2 doc 17, 60).

Covers the configuration fingerprint contract: every scan run stores a
fingerprint, and any key field change (connection_id, root_mapping_id,
storage_path, adapter_version, scan_schema_version) makes an old run
incompatible so it must not be resumed.

The domain tests (generation + field-by-field compatibility) run without a
database. The repository tests (find_resumable_run match/reject and
config-change invalidation) use a temporary SQLite database with the same
fixtures as the existing durable scan repository tests.
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from cloudsite.modules.indexing.domain.scan_fingerprint import (
    ScanFingerprint,
    generate_fingerprint,
)
from cloudsite.modules.indexing.infrastructure.durable_scan_repository import (
    DurableScanRepository,
)
from cloudsite.platform.db import StateBase


# ---------------------------------------------------------------------------
# Domain tests (no database)
# ---------------------------------------------------------------------------


def _sample_fingerprint(**overrides):
    base = dict(
        connection_id=7,
        root_mapping_id=1001,
        storage_path="/storage/docs",
        adapter_version="alist-1.2.3",
        scan_schema_version=2,
    )
    base.update(overrides)
    return generate_fingerprint(**base)


def test_fingerprint_generated():
    fp = generate_fingerprint(
        connection_id=7,
        root_mapping_id=1001,
        storage_path="/storage/docs",
        adapter_version="alist-1.2.3",
        scan_schema_version=2,
    )
    assert isinstance(fp, ScanFingerprint)
    assert fp.connection_id == 7
    assert fp.root_mapping_id == 1001
    assert fp.storage_path == "/storage/docs"
    assert fp.adapter_version == "alist-1.2.3"
    assert fp.scan_schema_version == 2
    as_dict = fp.to_dict()
    assert as_dict == {
        "connection_id": 7,
        "root_mapping_id": 1001,
        "storage_path": "/storage/docs",
        "adapter_version": "alist-1.2.3",
        "scan_schema_version": 2,
    }


def test_fingerprint_all_fields_match():
    a = _sample_fingerprint()
    b = _sample_fingerprint()
    assert a.is_compatible(b) is True
    assert b.is_compatible(a) is True


def test_fingerprint_connection_id_mismatch():
    a = _sample_fingerprint(connection_id=7)
    b = _sample_fingerprint(connection_id=8)
    assert a.is_compatible(b) is False
    assert b.is_compatible(a) is False


def test_fingerprint_storage_path_mismatch():
    a = _sample_fingerprint(storage_path="/storage/docs")
    b = _sample_fingerprint(storage_path="/storage/images")
    assert a.is_compatible(b) is False


def test_fingerprint_adapter_version_mismatch():
    a = _sample_fingerprint(adapter_version="alist-1.2.3")
    b = _sample_fingerprint(adapter_version="alist-1.2.4")
    assert a.is_compatible(b) is False


def test_fingerprint_schema_version_mismatch():
    a = _sample_fingerprint(scan_schema_version=2)
    b = _sample_fingerprint(scan_schema_version=3)
    assert a.is_compatible(b) is False


def test_fingerprint_root_mapping_id_mismatch():
    a = _sample_fingerprint(root_mapping_id=1001)
    b = _sample_fingerprint(root_mapping_id=1002)
    assert a.is_compatible(b) is False


def test_fingerprint_to_dict_is_stable_and_serializable():
    import json

    fp = _sample_fingerprint()
    serialized = json.dumps(fp.to_dict(), sort_keys=True)
    again = json.loads(serialized)
    assert again == fp.to_dict()


# ---------------------------------------------------------------------------
# Repository tests (temporary SQLite database)
# ---------------------------------------------------------------------------


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


def _repo_fingerprint_dict(**overrides):
    base = dict(
        connection_id=7,
        root_mapping_id=1001,
        storage_path="/storage/docs",
        adapter_version="alist-1.2.3",
        scan_schema_version=2,
    )
    base.update(overrides)
    return base


async def test_resumable_run_rejected_on_mismatch(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        old_fp = _repo_fingerprint_dict(adapter_version="alist-1.2.3")
        new_fp = _repo_fingerprint_dict(adapter_version="alist-1.2.4")

        async with factory() as session:
            root_id = await _seed_root_mapping(session)
            repo = DurableScanRepository(session)
            old_run = await repo.create_scan_run(root_id, fingerprint=old_fp)
            await repo.update_scan_run_status(old_run.id, "running")
            await session.commit()

        async with factory() as session:
            repo = DurableScanRepository(session)
            resumable = await repo.find_resumable_run(root_id, new_fp)
            assert resumable is None
    finally:
        await engine.dispose()


async def test_resumable_run_found_on_match(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        fp = _repo_fingerprint_dict()

        async with factory() as session:
            root_id = await _seed_root_mapping(session)
            repo = DurableScanRepository(session)
            run = await repo.create_scan_run(root_id, fingerprint=fp)
            await repo.update_scan_run_status(run.id, "running")
            await session.commit()
            run_id = run.id

        async with factory() as session:
            repo = DurableScanRepository(session)
            resumable = await repo.find_resumable_run(root_id, fp)
            assert resumable is not None
            assert resumable.id == run_id
            assert resumable.status == "running"
    finally:
        await engine.dispose()


async def test_config_change_invalidates_old_run(tmp_path):
    """Changing any key field makes the old run invisible to find_resumable_run."""
    engine, factory = await _make_engine(tmp_path)
    try:
        original = _repo_fingerprint_dict()

        async with factory() as session:
            root_id = await _seed_root_mapping(session)
            repo = DurableScanRepository(session)
            old_run = await repo.create_scan_run(root_id, fingerprint=original)
            await repo.update_scan_run_status(old_run.id, "running")
            await session.commit()
            old_run_id = old_run.id

        changed_configs = [
            _repo_fingerprint_dict(connection_id=8),
            _repo_fingerprint_dict(storage_path="/storage/images"),
            _repo_fingerprint_dict(adapter_version="alist-1.2.4"),
            _repo_fingerprint_dict(scan_schema_version=3),
        ]

        async with factory() as session:
            repo = DurableScanRepository(session)
            for changed in changed_configs:
                assert await repo.find_resumable_run(root_id, changed) is None

            assert await repo.find_resumable_run(root_id, original) is not None
            match = await repo.find_resumable_run(root_id, original)
            assert match.id == old_run_id
    finally:
        await engine.dispose()


async def test_find_resumable_run_ignores_terminal_status(tmp_path):
    """Completed/failed/cancelled runs are never resumable even on fp match."""
    engine, factory = await _make_engine(tmp_path)
    try:
        fp = _repo_fingerprint_dict()

        async with factory() as session:
            root_id = await _seed_root_mapping(session)
            repo = DurableScanRepository(session)
            completed = await repo.create_scan_run(root_id, fingerprint=fp)
            await repo.update_scan_run_status(completed.id, "running")
            await repo.update_scan_run_status(completed.id, "completed")
            await session.commit()

        async with factory() as session:
            repo = DurableScanRepository(session)
            assert await repo.find_resumable_run(root_id, fp) is None
    finally:
        await engine.dispose()


async def test_find_resumable_run_scoped_to_root_mapping(tmp_path):
    """A matching fingerprint on a different root is not returned."""
    engine, factory = await _make_engine(tmp_path)
    try:
        fp = _repo_fingerprint_dict(root_mapping_id=1001)

        async with factory() as session:
            root_a = await _seed_root_mapping(session, root_id=1001)
            root_b = await _seed_root_mapping(session, root_id=1002)
            repo = DurableScanRepository(session)
            run_a = await repo.create_scan_run(root_a, fingerprint=fp)
            await repo.update_scan_run_status(run_a.id, "running")
            await session.commit()

        async with factory() as session:
            repo = DurableScanRepository(session)
            assert await repo.find_resumable_run(1002, fp) is None
            assert await repo.find_resumable_run(1001, fp) is not None
    finally:
        await engine.dispose()
