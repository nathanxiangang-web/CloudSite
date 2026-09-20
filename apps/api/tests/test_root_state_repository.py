"""R5 PR01: RootStateRepository CRUD tests (V2 doc sections 6-7).

Exercises the repository layer over the index_root_states table introduced
in R5 PR01. All tests use temporary SQLite databases with PRAGMA
foreign_keys=ON so cascade-delete and FK semantics match production.
"""
from __future__ import annotations

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from cloudsite.modules.indexing.infrastructure.root_state_repository import (
    RootStateRepository,
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


async def test_table_created(tmp_path):
    """Migration creates index_root_states table with the expected columns."""
    engine, factory = await _make_engine(tmp_path)
    try:
        async with engine.connect() as conn:
            row = await conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='index_root_states'"
            )
            assert row.fetchone() is not None, "index_root_states table not created"

            cols = await conn.exec_driver_sql("PRAGMA table_info(index_root_states)")
            col_names = {r[1] for r in cols.fetchall()}
            assert col_names == {
                "root_mapping_id",
                "connection_id",
                "status",
                "generation",
                "bootstrap_completed_at",
                "last_change_at",
                "last_verified_at",
                "last_full_audit_at",
                "last_reconcile_at",
                "change_cursor",
                "provider_revision",
                "scan_fingerprint",
                "last_error_code",
                "last_error_message",
                "created_at",
                "updated_at",
            }
    finally:
        await engine.dispose()


async def test_upsert_and_get(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
            repo = RootStateRepository(session)
            await repo.upsert(root_id, connection_id=1, status="ready", generation=3)
            await session.commit()

        async with factory() as session:
            repo = RootStateRepository(session)
            record = await repo.get(root_id)
            assert record is not None
            assert record.root_mapping_id == root_id
            assert record.connection_id == 1
            assert record.status == "ready"
            assert record.generation == 3

            await repo.upsert(root_id, generation=4, change_cursor="abc")
            await session.commit()

        async with factory() as session:
            repo = RootStateRepository(session)
            record = await repo.get(root_id)
            assert record is not None
            assert record.generation == 4
            assert record.change_cursor == "abc"
            assert record.status == "ready"

            assert await repo.get(999999) is None
    finally:
        await engine.dispose()


async def test_update_status(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
            repo = RootStateRepository(session)
            await repo.upsert(root_id, connection_id=1)
            await session.commit()

            await repo.update_status(root_id, "bootstrapping")
            await session.commit()

        async with factory() as session:
            repo = RootStateRepository(session)
            record = await repo.get(root_id)
            assert record is not None
            assert record.status == "bootstrapping"
    finally:
        await engine.dispose()


async def test_find_by_status(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_a = await _seed_root_mapping(session, 2001)
            root_b = await _seed_root_mapping(session, 2002)
            root_c = await _seed_root_mapping(session, 2003)
            repo = RootStateRepository(session)
            await repo.upsert(root_a, connection_id=1, status="ready")
            await repo.upsert(root_b, connection_id=1, status="degraded")
            await repo.upsert(root_c, connection_id=1, status="ready")
            await session.commit()

        async with factory() as session:
            repo = RootStateRepository(session)
            ready = await repo.find_by_status("ready")
            assert len(ready) == 2
            assert {r.root_mapping_id for r in ready} == {root_a, root_c}
            assert all(r.status == "ready" for r in ready)

            degraded = await repo.find_by_status("degraded")
            assert len(degraded) == 1
            assert degraded[0].root_mapping_id == root_b

            assert await repo.find_by_status("disabled") == []
    finally:
        await engine.dispose()


async def test_delete(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
            repo = RootStateRepository(session)
            await repo.upsert(root_id, connection_id=1)
            await session.commit()

            await repo.delete(root_id)
            await session.commit()

        async with factory() as session:
            repo = RootStateRepository(session)
            assert await repo.get(root_id) is None
    finally:
        await engine.dispose()


async def test_default_status(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
            repo = RootStateRepository(session)
            await repo.upsert(root_id, connection_id=1)
            await session.commit()

        async with factory() as session:
            repo = RootStateRepository(session)
            record = await repo.get(root_id)
            assert record is not None
            assert record.status == "bootstrap_required"
    finally:
        await engine.dispose()


async def test_generation_default_zero(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
            repo = RootStateRepository(session)
            await repo.upsert(root_id, connection_id=1)
            await session.commit()

        async with factory() as session:
            repo = RootStateRepository(session)
            record = await repo.get(root_id)
            assert record is not None
            assert record.generation == 0
    finally:
        await engine.dispose()


async def test_cascade_delete_root_mapping(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
            repo = RootStateRepository(session)
            await repo.upsert(root_id, connection_id=1, status="ready")
            await session.commit()

        async with factory() as session:
            await session.execute(
                text("DELETE FROM content_root_mappings WHERE id = :id"),
                {"id": root_id},
            )
            await session.commit()

        async with factory() as session:
            repo = RootStateRepository(session)
            assert await repo.get(root_id) is None
            count = (
                await session.execute(
                    text("SELECT COUNT(*) FROM index_root_states")
                )
            ).scalar_one()
            assert count == 0
    finally:
        await engine.dispose()


async def test_upsert_rejects_unknown_field(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
            repo = RootStateRepository(session)
            with pytest.raises(ValueError):
                await repo.upsert(root_id, connection_id=1, bogus_field=1)
    finally:
        await engine.dispose()


async def test_upsert_requires_connection_id_for_new_row(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
            repo = RootStateRepository(session)
            with pytest.raises(ValueError):
                await repo.upsert(root_id, status="ready")
    finally:
        await engine.dispose()
