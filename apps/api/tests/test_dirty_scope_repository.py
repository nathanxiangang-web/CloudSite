"""R6 PR01: DirtyScopeRepository CRUD tests (V2 doc section 29).

Exercises the repository layer over the index_dirty_scopes table introduced
in R6 PR01. All tests use temporary SQLite databases with
PRAGMA foreign_keys=ON so cascade-delete and FK semantics match production.
"""
from __future__ import annotations

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from cloudsite.modules.indexing.infrastructure.dirty_scope_repository import (
    DirtyScopeRepository,
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


async def test_table_created(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with engine.connect() as conn:
            row = await conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='index_dirty_scopes'"
            )
            assert row.fetchone() is not None, "index_dirty_scopes table not created"
    finally:
        await engine.dispose()


async def test_add_and_get(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
            repo = DirtyScopeRepository(session)
            dirty_id = await repo.add(root_id, "/docs", reason="verification_mismatch", priority=3)
            await session.commit()

        async with factory() as session:
            repo = DirtyScopeRepository(session)
            record = await repo.get(dirty_id)
            assert record is not None
            assert record.id == dirty_id
            assert record.root_mapping_id == root_id
            assert record.path == "/docs"
            assert record.reason == "verification_mismatch"
            assert record.priority == 3
            assert record.status == "pending"
            assert record.attempts == 0
            assert record.detected_at is not None
            assert record.updated_at is not None
            assert record.last_error_code is None
            assert record.last_error_message is None

            missing = await repo.get(999999)
            assert missing is None
    finally:
        await engine.dispose()


async def test_find_pending(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
            repo = DirtyScopeRepository(session)
            id_a = await repo.add(root_id, "/a", priority=1)
            id_b = await repo.add(root_id, "/b", priority=5)
            id_c = await repo.add(root_id, "/c", priority=3)
            await session.commit()

            await repo.update_status(id_a, "processing")
            await session.commit()

        async with factory() as session:
            repo = DirtyScopeRepository(session)
            pending = await repo.find_pending(root_id)
            pending_ids = [r.id for r in pending]
            assert pending_ids == [id_b, id_c], "pending should be ordered by priority DESC"

            other = await repo.find_pending(999999)
            assert other == []
    finally:
        await engine.dispose()


async def test_update_status(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
            repo = DirtyScopeRepository(session)
            dirty_id = await repo.add(root_id, "/x")
            await session.commit()

            await repo.update_status(dirty_id, "processing")
            await session.commit()

        async with factory() as session:
            repo = DirtyScopeRepository(session)
            record = await repo.get(dirty_id)
            assert record is not None
            assert record.status == "processing"
            assert record.last_error_code is None
            assert record.last_error_message is None

            await repo.update_status(
                dirty_id, "failed", error_code="E_TIMEOUT", error_message="scan timed out"
            )
            await session.commit()

        async with factory() as session:
            repo = DirtyScopeRepository(session)
            record = await repo.get(dirty_id)
            assert record is not None
            assert record.status == "failed"
            assert record.last_error_code == "E_TIMEOUT"
            assert record.last_error_message == "scan timed out"

        async with factory() as session:
            repo = DirtyScopeRepository(session)
            escalated = await repo.find_by_status("failed")
            assert any(r.id == dirty_id for r in escalated)
    finally:
        await engine.dispose()


async def test_increment_attempts(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
            repo = DirtyScopeRepository(session)
            dirty_id = await repo.add(root_id, "/y")
            await session.commit()

            for _ in range(3):
                await repo.increment_attempts(dirty_id)
            await session.commit()

        async with factory() as session:
            repo = DirtyScopeRepository(session)
            record = await repo.get(dirty_id)
            assert record is not None
            assert record.attempts == 3
    finally:
        await engine.dispose()


async def test_resolve(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session)
            repo = DirtyScopeRepository(session)
            dirty_id = await repo.add(root_id, "/z")
            await session.commit()

            await repo.update_status(dirty_id, "processing")
            await session.commit()

            await repo.resolve(dirty_id)
            await session.commit()

        async with factory() as session:
            repo = DirtyScopeRepository(session)
            record = await repo.get(dirty_id)
            assert record is not None
            assert record.status == "resolved"

            resolved = await repo.find_by_status("resolved")
            assert any(r.id == dirty_id for r in resolved)
            pending = await repo.find_pending(root_id)
            assert all(r.id != dirty_id for r in pending)
    finally:
        await engine.dispose()


async def test_exists(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session, root_id=2001)
            repo = DirtyScopeRepository(session)
            await repo.add(root_id, "/exists")
            await session.commit()

        async with factory() as session:
            repo = DirtyScopeRepository(session)
            assert await repo.exists(root_id, "/exists") is True
            assert await repo.exists(root_id, "/missing") is False
            assert await repo.exists(999999, "/exists") is False
    finally:
        await engine.dispose()


async def test_unique_constraint(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session, root_id=3001)
            repo = DirtyScopeRepository(session)
            await repo.add(root_id, "/dup")
            await session.commit()

        async with factory() as session:
            repo = DirtyScopeRepository(session)
            with pytest.raises(Exception):
                await repo.add(root_id, "/dup")
            await session.rollback()

        async with factory() as session:
            repo = DirtyScopeRepository(session)
            other_root = await _seed_root_mapping(session, root_id=3002)
            await repo.add(other_root, "/dup")
            await session.commit()

            assert await repo.exists(root_id, "/dup") is True
            assert await repo.exists(other_root, "/dup") is True
    finally:
        await engine.dispose()


async def test_cascade_delete_root_mapping(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session, root_id=4001)
            repo = DirtyScopeRepository(session)
            dirty_id = await repo.add(root_id, "/cascade")
            await session.commit()

        async with factory() as session:
            repo = DirtyScopeRepository(session)
            assert await repo.get(dirty_id) is not None

        async with factory() as session:
            await session.execute(
                text("DELETE FROM content_root_mappings WHERE id = :id"),
                {"id": root_id},
            )
            await session.commit()

        async with factory() as session:
            repo = DirtyScopeRepository(session)
            assert await repo.get(dirty_id) is None
            count = (
                await session.execute(
                    text("SELECT COUNT(*) FROM index_dirty_scopes")
                )
            ).scalar_one()
            assert count == 0
    finally:
        await engine.dispose()


async def test_default_values(tmp_path):
    engine, factory = await _make_engine(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root_mapping(session, root_id=5001)
            repo = DirtyScopeRepository(session)
            dirty_id = await repo.add(root_id, "/defaults")
            await session.commit()

        async with factory() as session:
            repo = DirtyScopeRepository(session)
            record = await repo.get(dirty_id)
            assert record is not None
            assert record.status == "pending"
            assert record.attempts == 0
            assert record.priority == 0
            assert record.reason == "verification_mismatch"
            assert record.detected_at is not None
            assert record.updated_at is not None
    finally:
        await engine.dispose()
