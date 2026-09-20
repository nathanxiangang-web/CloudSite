"""R2 PR01: durable scan state migration v30->v31 (V2 doc sections 11-13).

Exercises:
- test_tables_created: migration creates index_scan_runs, index_scan_dirs,
  index_scan_entries on a fresh database and reaches the current schema version
- test_columns_correct: each table has the exact column set required by the
  V2 durable scan contract
- test_foreign_keys: index_scan_runs.root_mapping_id -> content_root_mappings.id
  and index_scan_dirs/index_scan_entries.scan_run_id -> index_scan_runs.id are
  enforced (inserting a row with a dangling FK fails)
- test_unique_constraints: index_scan_dirs (scan_run_id, path) uniqueness holds
- test_indexes: the indexes needed for resume/queue queries exist
  (scan_run_id, status, root_mapping_id, composite scan_run_id+status)

All tests use temporary databases only.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import event, inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from cloudsite import database
from cloudsite.database import StateBase
from cloudsite.migrations import CURRENT_SCHEMA_VERSION, get_state_schema_version


def _enable_foreign_keys(engine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn, _record):  # noqa: ANN001
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


EXPECTED_RUN_COLUMNS = {
    "id",
    "root_mapping_id",
    "status",
    "started_at",
    "finished_at",
    "fingerprint",
    "total_dirs",
    "total_entries",
    "error_message",
}

EXPECTED_DIR_COLUMNS = {
    "id",
    "scan_run_id",
    "path",
    "depth",
    "status",
    "started_at",
    "finished_at",
    "entry_count",
    "error_message",
}

EXPECTED_ENTRY_COLUMNS = {
    "id",
    "scan_run_id",
    "dir_path",
    "resource_id",
    "name",
    "is_dir",
    "modified",
    "metadata_hash",
    "staged_at",
}

DURABLE_TABLES = ("index_scan_runs", "index_scan_dirs", "index_scan_entries")


async def _init_engines(tmp_path, monkeypatch):
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    _enable_foreign_keys(state_engine)
    _enable_foreign_keys(index_engine)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()
    return state_engine, index_engine


async def test_tables_created(tmp_path, monkeypatch):
    state_engine, index_engine = await _init_engines(tmp_path, monkeypatch)

    async with state_engine.connect() as conn:
        assert await get_state_schema_version(conn) == CURRENT_SCHEMA_VERSION
        for table in DURABLE_TABLES:
            row = await conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=:n",
                {"n": table},
            )
            assert row.fetchone() is not None, f"table {table} not created"

    await state_engine.dispose()
    await index_engine.dispose()


async def test_columns_correct(tmp_path, monkeypatch):
    state_engine, index_engine = await _init_engines(tmp_path, monkeypatch)

    async with state_engine.connect() as conn:
        runs = await conn.exec_driver_sql("PRAGMA table_info(index_scan_runs)")
        assert {row[1] for row in runs.fetchall()} == EXPECTED_RUN_COLUMNS

        dirs = await conn.exec_driver_sql("PRAGMA table_info(index_scan_dirs)")
        assert {row[1] for row in dirs.fetchall()} == EXPECTED_DIR_COLUMNS

        entries = await conn.exec_driver_sql("PRAGMA table_info(index_scan_entries)")
        assert {row[1] for row in entries.fetchall()} == EXPECTED_ENTRY_COLUMNS

        runs_pk = await conn.exec_driver_sql("PRAGMA table_info(index_scan_runs)")
        pk_cols = {row[1] for row in runs_pk.fetchall() if row[5] == 1}
        assert pk_cols == {"id"}, f"unexpected PK on index_scan_runs: {pk_cols}"

    await state_engine.dispose()
    await index_engine.dispose()


async def test_foreign_keys(tmp_path, monkeypatch):
    state_engine, index_engine = await _init_engines(tmp_path, monkeypatch)

    async with state_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO content_root_mappings "
                "(id, connection_id, content_type, display_name, alist_path, enabled, "
                "sort_order, home_order, created_at, updated_at) "
                "VALUES (501, 1, 'software', 'root-a', '/a', 1, 0, 0, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        run_id = str(uuid.uuid4())
        await conn.execute(
            text(
                "INSERT INTO index_scan_runs "
                "(id, root_mapping_id, status, started_at, fingerprint) "
                "VALUES (:id, 501, 'running', CURRENT_TIMESTAMP, 'fp-1')"
            ),
            {"id": run_id},
        )

    async with state_engine.begin() as conn:
        with pytest.raises(Exception):
            await conn.execute(
                text(
                    "INSERT INTO index_scan_runs "
                    "(id, root_mapping_id, status, started_at) "
                    "VALUES (:id, 999999, 'pending', CURRENT_TIMESTAMP)"
                ),
                {"id": str(uuid.uuid4())},
            )

    async with state_engine.begin() as conn:
        with pytest.raises(Exception):
            await conn.execute(
                text(
                    "INSERT INTO index_scan_dirs "
                    "(id, scan_run_id, path, depth, status) "
                    "VALUES (:id, 'nonexistent-run', '/x', 0, 'pending')"
                ),
                {"id": str(uuid.uuid4())},
            )

    async with state_engine.begin() as conn:
        with pytest.raises(Exception):
            await conn.execute(
                text(
                    "INSERT INTO index_scan_entries "
                    "(id, scan_run_id, dir_path, resource_id, name, is_dir) "
                    "VALUES (:id, 'nonexistent-run', '/x', 'res-1', 'name', 0)"
                ),
                {"id": str(uuid.uuid4())},
            )

    await state_engine.dispose()
    await index_engine.dispose()


async def test_unique_constraints(tmp_path, monkeypatch):
    state_engine, index_engine = await _init_engines(tmp_path, monkeypatch)

    async with state_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO content_root_mappings "
                "(id, connection_id, content_type, display_name, alist_path, enabled, "
                "sort_order, home_order, created_at, updated_at) "
                "VALUES (601, 1, 'software', 'root-b', '/b', 1, 0, 0, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        run_id = str(uuid.uuid4())
        await conn.execute(
            text(
                "INSERT INTO index_scan_runs "
                "(id, root_mapping_id, status, started_at) "
                "VALUES (:id, 601, 'running', CURRENT_TIMESTAMP)"
            ),
            {"id": run_id},
        )
        await conn.execute(
            text(
                "INSERT INTO index_scan_dirs "
                "(id, scan_run_id, path, depth, status) "
                "VALUES (:id, :run, '/same/path', 1, 'pending')"
            ),
            {"id": str(uuid.uuid4()), "run": run_id},
        )

    async with state_engine.begin() as conn:
        with pytest.raises(Exception):
            await conn.execute(
                text(
                    "INSERT INTO index_scan_dirs "
                    "(id, scan_run_id, path, depth, status) "
                    "VALUES (:id, :run, '/same/path', 1, 'pending')"
                ),
                {"id": str(uuid.uuid4()), "run": run_id},
            )

    async with state_engine.begin() as conn:
        other_run = str(uuid.uuid4())
        await conn.execute(
            text(
                "INSERT INTO index_scan_runs "
                "(id, root_mapping_id, status, started_at) "
                "VALUES (:id, 601, 'running', CURRENT_TIMESTAMP)"
            ),
            {"id": other_run},
        )
        await conn.execute(
            text(
                "INSERT INTO index_scan_dirs "
                "(id, scan_run_id, path, depth, status) "
                "VALUES (:id, :run, '/same/path', 1, 'pending')"
            ),
            {"id": str(uuid.uuid4()), "run": other_run},
        )

    await state_engine.dispose()
    await index_engine.dispose()


async def test_indexes(tmp_path, monkeypatch):
    state_engine, index_engine = await _init_engines(tmp_path, monkeypatch)

    def _index_names(sync_conn):
        inspector = inspect(sync_conn)
        result: dict[str, set[str]] = {}
        for table in DURABLE_TABLES:
            result[table] = {idx["name"] for idx in inspector.get_indexes(table)}
        return result

    async with state_engine.connect() as conn:
        names = await conn.run_sync(_index_names)

    assert "ix_index_scan_runs_root_mapping_id" in names["index_scan_runs"]
    assert "ix_index_scan_runs_status" in names["index_scan_runs"]
    assert "ix_index_scan_dirs_scan_run_id" in names["index_scan_dirs"]
    assert "ix_index_scan_dirs_status" in names["index_scan_dirs"]
    assert "ix_index_scan_dirs_scan_run_status" in names["index_scan_dirs"]
    assert "ix_index_scan_entries_scan_run_id" in names["index_scan_entries"]
    assert "ix_index_scan_entries_resource_id" in names["index_scan_entries"]

    await state_engine.dispose()
    await index_engine.dispose()


async def test_v30_to_v31_idempotent(tmp_path, monkeypatch):
    state_engine, index_engine = await _init_engines(tmp_path, monkeypatch)
    await database.init_databases()

    async with state_engine.connect() as conn:
        assert await get_state_schema_version(conn) == CURRENT_SCHEMA_VERSION
        for table in DURABLE_TABLES:
            row = await conn.exec_driver_sql(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=:n",
                {"n": table},
            )
            assert row.fetchone()[0] == 1, f"table {table} duplicated on re-init"

    await state_engine.dispose()
    await index_engine.dispose()


async def test_old_v30_db_upgrades_to_v31(tmp_path, monkeypatch):
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    _enable_foreign_keys(state_engine)
    _enable_foreign_keys(index_engine)
    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
        await conn.execute(
            text(
                "INSERT INTO content_root_mappings "
                "(id, connection_id, content_type, display_name, alist_path, enabled, "
                "sort_order, home_order, created_at, updated_at) "
                "VALUES (701, 1, 'software', 'root-c', '/c', 1, 0, 0, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        from cloudsite.migrations import set_state_schema_version
        await set_state_schema_version(conn, 30)

    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    async with state_engine.connect() as conn:
        assert await get_state_schema_version(conn) == CURRENT_SCHEMA_VERSION
        roots = (await conn.execute(text("SELECT COUNT(*) FROM content_root_mappings"))).scalar_one()
        assert roots == 1
        for table in DURABLE_TABLES:
            row = await conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=:n",
                {"n": table},
            )
            assert row.fetchone() is not None, f"table {table} missing after upgrade"

    await state_engine.dispose()
    await index_engine.dispose()
