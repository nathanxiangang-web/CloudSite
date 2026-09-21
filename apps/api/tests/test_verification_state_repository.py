"""R8 durable per-directory verification state regressions."""

from __future__ import annotations

import pytest
from sqlalchemy import event, inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from cloudsite import database
from cloudsite.migrations import (
    CURRENT_SCHEMA_VERSION,
    get_state_schema_version,
    set_state_schema_version,
)
from cloudsite.modules.indexing.infrastructure.verification_state_repository import (
    VerificationStateRepository,
)
from cloudsite.platform.db import IndexBase, StateBase


def _enable_foreign_keys(engine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn, _record):  # noqa: ANN001
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


async def _state_store(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    _enable_foreign_keys(engine)
    async with engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, factory


async def _seed_root(session: AsyncSession, root_id: int = 4001) -> int:
    await session.execute(
        text(
            "INSERT INTO content_root_mappings "
            "(id, connection_id, content_type, display_name, alist_path, enabled, "
            "sort_order, home_order, created_at, updated_at) "
            "VALUES (:id, 1, 'software', :name, :path, 1, 0, 0, "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {"id": root_id, "name": f"root-{root_id}", "path": f"/root-{root_id}"},
    )
    await session.commit()
    return root_id


async def test_verification_state_table_shape(tmp_path):
    engine, _ = await _state_store(tmp_path)
    try:
        async with engine.connect() as conn:
            columns = await conn.exec_driver_sql(
                "PRAGMA table_info(index_verification_states)"
            )
            assert {row[1] for row in columns.fetchall()} == {
                "root_mapping_id",
                "path",
                "fingerprint",
                "child_count",
                "last_verified_at",
                "last_changed_at",
                "last_error_code",
                "last_error_message",
                "created_at",
                "updated_at",
            }

            def _indexes(sync_conn):
                return {
                    item["name"]
                    for item in inspect(sync_conn).get_indexes(
                        "index_verification_states"
                    )
                }

            indexes = await conn.run_sync(_indexes)
            assert "ix_index_verification_states_root_verified" in indexes
            assert "ix_index_verification_states_last_changed" in indexes
    finally:
        await engine.dispose()


async def test_mark_verified_persists_baseline_and_clears_error(tmp_path):
    engine, factory = await _state_store(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root(session)
            repo = VerificationStateRepository(session)
            await repo.mark_failed(
                root_id,
                "/apps",
                error_code="provider_unavailable",
                error_message="temporary failure",
            )
            await session.commit()

            await repo.mark_verified(
                root_id,
                "/apps",
                fingerprint="fp-1",
                child_count=12,
                changed=True,
                verified_at="2026-09-21T05:00:00+00:00",
            )
            await session.commit()

        async with factory() as session:
            record = await VerificationStateRepository(session).get(root_id, "/apps")
            assert record is not None
            assert record.fingerprint == "fp-1"
            assert record.child_count == 12
            assert record.last_verified_at == "2026-09-21T05:00:00+00:00"
            assert record.last_changed_at == "2026-09-21T05:00:00+00:00"
            assert record.last_error_code is None
            assert record.last_error_message is None
    finally:
        await engine.dispose()


async def test_list_for_root_prioritizes_never_verified_then_oldest(tmp_path):
    engine, factory = await _state_store(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root(session)
            repo = VerificationStateRepository(session)
            await repo.upsert(root_id, "/never")
            await repo.mark_verified(
                root_id,
                "/newer",
                fingerprint="n",
                child_count=1,
                verified_at="2026-09-21T05:00:00+00:00",
            )
            await repo.mark_verified(
                root_id,
                "/older",
                fingerprint="o",
                child_count=1,
                verified_at="2026-09-20T05:00:00+00:00",
            )
            await session.commit()

        async with factory() as session:
            rows = await VerificationStateRepository(session).list_for_root(root_id)
            assert [row.path for row in rows] == ["/never", "/older", "/newer"]
    finally:
        await engine.dispose()


async def test_root_delete_cascades_verification_state(tmp_path):
    engine, factory = await _state_store(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root(session)
            repo = VerificationStateRepository(session)
            await repo.mark_verified(
                root_id,
                "/apps",
                fingerprint="fp",
                child_count=2,
            )
            await session.commit()

            await session.execute(
                text("DELETE FROM content_root_mappings WHERE id = :rid"),
                {"rid": root_id},
            )
            await session.commit()

        async with factory() as session:
            assert (
                await VerificationStateRepository(session).get(root_id, "/apps")
                is None
            )
    finally:
        await engine.dispose()


async def test_upsert_rejects_unknown_fields(tmp_path):
    engine, factory = await _state_store(tmp_path)
    try:
        async with factory() as session:
            root_id = await _seed_root(session)
            repo = VerificationStateRepository(session)
            with pytest.raises(ValueError, match="unsupported"):
                await repo.upsert(root_id, "/apps", bogus=True)
    finally:
        await engine.dispose()


async def test_v33_database_migrates_to_v34(tmp_path, monkeypatch):
    state_engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'state-migration.db'}"
    )
    index_engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'index-migration.db'}"
    )
    _enable_foreign_keys(state_engine)
    _enable_foreign_keys(index_engine)

    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
        await conn.exec_driver_sql("DROP TABLE index_verification_states")
        await set_state_schema_version(conn, 33)
    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)

    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    try:
        async with state_engine.connect() as conn:
            assert await get_state_schema_version(conn) == CURRENT_SCHEMA_VERSION
            row = await conn.exec_driver_sql(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='index_verification_states'"
            )
            assert row.fetchone() is not None
    finally:
        await state_engine.dispose()
        await index_engine.dispose()
