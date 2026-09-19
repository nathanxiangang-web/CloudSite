"""Focused schema tests for the durable parser candidate task boundary.

Covers the persistence boundary only:
- fresh initialization reaches schema v8 and creates parser_candidate_tasks
  with conservative defaults (status='pending', retry_count=0, completed_at
  NULL, result_json NULL, error_text NULL)
- a synthetic v1.3 (schema_version=7) state.db with existing C1/C2 catalog
  rows upgrades to v8; catalog rows survive unchanged and the new table exists
- repeated initialization is idempotent (no duplicate tables/indexes, version
  stable)
- duplicate input for the same parser version is rejected at the database
  boundary by the UNIQUE (resource_id, input_fingerprint, parser_version)
  constraint
- statuses are constrained to pending, running, completed, failed, cancelled;
  any other value is rejected at the database boundary
- a durable pending task survives database reopen (process restart)
- a completed task stores the parser result as JSON text without overwriting
  any Catalog fields

No scheduler, retry, router, or suggestion application is exercised here.
Full API, recovery, and cross-version regression are deferred to the
verification phase.
"""
import json

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import database, models  # noqa: F401 - register ORM metadata
from cloudsite.database import IndexBase, StateBase
from cloudsite.migrations import (
    CURRENT_SCHEMA_VERSION,
    get_state_schema_version,
    get_index_schema_version,
)

TASK_TABLE = "parser_candidate_tasks"


def _engines(tmp_path):
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    return state_engine, index_engine


async def _table_names(conn) -> set[str]:
    return await conn.run_sync(lambda sync_conn: set(inspect(sync_conn).get_table_names()))


async def _columns(conn, table: str) -> set[str]:
    return await conn.run_sync(
        lambda sync_conn: {column["name"] for column in inspect(sync_conn).get_columns(table)}
    )


async def _index_names(conn, table: str) -> set[str]:
    return await conn.run_sync(
        lambda sync_conn: {ix["name"] for ix in inspect(sync_conn).get_indexes(table)}
    )


async def test_fresh_init_creates_parser_candidate_tasks_table(tmp_path, monkeypatch):
    """Fresh databases reach schema v8 and contain parser_candidate_tasks."""
    state_engine, index_engine = _engines(tmp_path)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)

    await database.init_databases()

    async with state_engine.connect() as conn:
        assert await get_state_schema_version(conn) == CURRENT_SCHEMA_VERSION
                tables = await _table_names(conn)
        assert TASK_TABLE in tables, f"missing table {TASK_TABLE}"

        cols = await _columns(conn, TASK_TABLE)
        expected = {
            "task_id", "resource_id", "input_fingerprint", "parser_version",
            "status", "retry_count", "result_json", "error_text",
            "created_at", "updated_at", "completed_at",
        }
        assert set(cols) == expected, set(cols) ^ expected

        indexes = await _index_names(conn, TASK_TABLE)
        for ix in (
            "ix_parser_candidate_tasks_status",
            "ix_parser_candidate_tasks_resource_id",
            "ix_parser_candidate_tasks_parser_version",
        ):
            assert ix in indexes, f"missing index {ix}"

    async with index_engine.connect() as conn:
        assert await get_index_schema_version(conn) == CURRENT_SCHEMA_VERSION

    await state_engine.dispose()
    await index_engine.dispose()


async def test_default_values_on_insert(tmp_path, monkeypatch):
    """A row inserted with only required fields gets conservative defaults."""
    state_engine, index_engine = _engines(tmp_path)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    factory = async_sessionmaker(state_engine, expire_on_commit=False)
    async with factory() as session:
        session.add(
            models.ParserCandidateTask(
                task_id="pt_" + "a" * 32,
                resource_id="r_" + "b" * 32,
                input_fingerprint="fp_" + "c" * 30,
                parser_version="1.0.0",
            )
        )
        await session.commit()

    async with state_engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT status, retry_count, result_json, error_text, completed_at "
                    f"FROM {TASK_TABLE} WHERE task_id=:tid"
                ),
                {"tid": "pt_" + "a" * 32},
            )
        ).one()
        assert row[0] == "pending"
        assert row[1] == 0
        assert row[2] is None
        assert row[3] is None
        assert row[4] is None

    await state_engine.dispose()
    await index_engine.dispose()


async def test_synthetic_v7_upgrades_to_v8_preserving_catalog_rows(tmp_path, monkeypatch):
    """A synthetic v1.3 (schema_version=7) state.db with existing C1/C2 catalog
    rows upgrades to v8. Catalog rows survive unchanged; the new table exists."""
    state_engine, index_engine = _engines(tmp_path)

    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
        await conn.execute(
            text(
                "INSERT OR REPLACE INTO system_settings(key, value, value_type, updated_at) "
                "VALUES('schema_version', '7', 'integer', CURRENT_TIMESTAMP)"
            )
        )

    factory = async_sessionmaker(state_engine, expire_on_commit=False)
    async with factory() as session:
        entry = models.CatalogEntry(
            entry_id="ce_survive_v8",
            content_type="software",
            slug="legacy-app",
            title="Legacy App",
            status="published",
            revision=3,
        )
        release = models.CatalogRelease(
            release_id="cr_survive_v8",
            entry_id=entry.entry_id,
            slug="2.0",
            title="2.0",
            status="published",
            channel="stable",
        )
        asset = models.CatalogAsset(
            asset_id="ca_survive_v8",
            release_id=release.release_id,
            slug="linux-tar",
            display_name="app-2.0-linux.tar.gz",
            kind="file",
            architecture="x64",
            package_type="tar_gz",
        )
        session.add_all([entry, release, asset])
        await session.commit()

    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)

    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    async with state_engine.connect() as conn:
        assert await get_state_schema_version(conn) == CURRENT_SCHEMA_VERSION
        
        entry_row = (
            await conn.execute(
                text("SELECT title, revision FROM catalog_entries WHERE entry_id='ce_survive_v8'")
            )
        ).one()
        assert entry_row[0] == "Legacy App"
        assert entry_row[1] == 3

        release_row = (
            await conn.execute(
                text(
                    "SELECT slug, status, channel "
                    "FROM catalog_releases WHERE release_id='cr_survive_v8'"
                )
            )
        ).one()
        assert release_row[0] == "2.0"
        assert release_row[1] == "published"
        assert release_row[2] == "stable"

        asset_row = (
            await conn.execute(
                text(
                    "SELECT display_name, architecture, package_type "
                    "FROM catalog_assets WHERE asset_id='ca_survive_v8'"
                )
            )
        ).one()
        assert asset_row[0] == "app-2.0-linux.tar.gz"
        assert asset_row[1] == "x64"
        assert asset_row[2] == "tar_gz"

        tables = await _table_names(conn)
        assert TASK_TABLE in tables
        count = (await conn.execute(text(f"SELECT COUNT(*) FROM {TASK_TABLE}"))).scalar_one()
        assert count == 0

    await state_engine.dispose()
    await index_engine.dispose()


async def test_repeated_init_is_idempotent_v8(tmp_path, monkeypatch):
    """Re-running initialization does not duplicate tables/indexes and keeps
    version stable at v8."""
    state_engine, index_engine = _engines(tmp_path)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)

    await database.init_databases()

    async with state_engine.connect() as conn:
        cols_before = await _columns(conn, TASK_TABLE)
        idx_before = await _index_names(conn, TASK_TABLE)

    await database.init_databases()
    await database.init_databases()

    async with state_engine.connect() as conn:
        assert await get_state_schema_version(conn) == CURRENT_SCHEMA_VERSION
        assert await _columns(conn, TASK_TABLE) == cols_before
        assert await _index_names(conn, TASK_TABLE) == idx_before

    await state_engine.dispose()
    await index_engine.dispose()


async def test_duplicate_input_for_same_parser_version_rejected(tmp_path, monkeypatch):
    """Duplicate (resource_id, input_fingerprint, parser_version) is rejected at
    the database boundary."""
    state_engine, index_engine = _engines(tmp_path)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    factory = async_sessionmaker(state_engine, expire_on_commit=False)
    resource_id = "r_dup_" + "d" * 28
    fingerprint = "fp_dup_" + "e" * 28
    async with factory() as session:
        session.add(
            models.ParserCandidateTask(
                task_id="pt_dup_1",
                resource_id=resource_id,
                input_fingerprint=fingerprint,
                parser_version="1.0.0",
            )
        )
        await session.commit()

    async with factory() as session:
        session.add(
            models.ParserCandidateTask(
                task_id="pt_dup_2",
                resource_id=resource_id,
                input_fingerprint=fingerprint,
                parser_version="1.0.0",
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()

    async with state_engine.connect() as conn:
        count = (
            await conn.execute(
                text(
                    f"SELECT COUNT(*) FROM {TASK_TABLE} "
                    "WHERE resource_id=:rid AND input_fingerprint=:fp AND parser_version='1.0.0'"
                ),
                {"rid": resource_id, "fp": fingerprint},
            )
        ).scalar_one()
        assert count == 1

    await state_engine.dispose()
    await index_engine.dispose()


async def test_same_resource_different_parser_version_allowed(tmp_path, monkeypatch):
    """The same resource and fingerprint with a different parser version is
    allowed (re-parse after a parser upgrade)."""
    state_engine, index_engine = _engines(tmp_path)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    factory = async_sessionmaker(state_engine, expire_on_commit=False)
    resource_id = "r_reparse_" + "f" * 26
    fingerprint = "fp_reparse_" + "0" * 26
    async with factory() as session:
        session.add(
            models.ParserCandidateTask(
                task_id="pt_reparse_1",
                resource_id=resource_id,
                input_fingerprint=fingerprint,
                parser_version="1.0.0",
                status="completed",
            )
        )
        session.add(
            models.ParserCandidateTask(
                task_id="pt_reparse_2",
                resource_id=resource_id,
                input_fingerprint=fingerprint,
                parser_version="1.1.0",
            )
        )
        await session.commit()

    async with state_engine.connect() as conn:
        count = (
            await conn.execute(
                text(
                    f"SELECT COUNT(*) FROM {TASK_TABLE} "
                    "WHERE resource_id=:rid AND input_fingerprint=:fp"
                ),
                {"rid": resource_id, "fp": fingerprint},
            )
        ).scalar_one()
        assert count == 2

    await state_engine.dispose()
    await index_engine.dispose()


async def test_invalid_status_rejected(tmp_path, monkeypatch):
    """A status outside the allowed set is rejected at the database boundary."""
    state_engine, index_engine = _engines(tmp_path)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    factory = async_sessionmaker(state_engine, expire_on_commit=False)
    async with factory() as session:
        session.add(
            models.ParserCandidateTask(
                task_id="pt_bad_status",
                resource_id="r_bad",
                input_fingerprint="fp_bad",
                parser_version="1.0.0",
                status="queued",
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()

    await state_engine.dispose()
    await index_engine.dispose()


async def test_all_allowed_statuses_persist(tmp_path, monkeypatch):
    """Every allowed status value persists without error."""
    state_engine, index_engine = _engines(tmp_path)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    factory = async_sessionmaker(state_engine, expire_on_commit=False)
    allowed = ("pending", "running", "completed", "failed", "cancelled")
    async with factory() as session:
        for index, status in enumerate(allowed):
            session.add(
                models.ParserCandidateTask(
                    task_id=f"pt_status_{index}",
                    resource_id=f"r_status_{index}",
                    input_fingerprint=f"fp_status_{index}",
                    parser_version="1.0.0",
                    status=status,
                )
            )
        await session.commit()

    async with state_engine.connect() as conn:
        rows = (
            await conn.execute(text(f"SELECT status FROM {TASK_TABLE} ORDER BY task_id"))
        ).all()
        assert {row[0] for row in rows} == set(allowed)

    await state_engine.dispose()
    await index_engine.dispose()


async def test_pending_task_survives_database_reopen(tmp_path, monkeypatch):
    """A durable pending task survives closing and reopening the database
    (process restart)."""
    state_engine, index_engine = _engines(tmp_path)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    task_id = "pt_reopen_" + "1" * 30
    resource_id = "r_reopen_" + "2" * 29
    fingerprint = "fp_reopen_" + "3" * 28

    factory = async_sessionmaker(state_engine, expire_on_commit=False)
    async with factory() as session:
        session.add(
            models.ParserCandidateTask(
                task_id=task_id,
                resource_id=resource_id,
                input_fingerprint=fingerprint,
                parser_version="1.0.0",
                status="pending",
            )
        )
        await session.commit()

    await state_engine.dispose()
    await index_engine.dispose()

    reopened_state = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    reopened_index = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    monkeypatch.setattr(database, "state_engine", reopened_state)
    monkeypatch.setattr(database, "index_engine", reopened_index)
    await database.init_databases()

    async with reopened_state.connect() as conn:
        assert await get_state_schema_version(conn) == CURRENT_SCHEMA_VERSION
        row = (
            await conn.execute(
                text(
                    "SELECT task_id, resource_id, input_fingerprint, parser_version, status "
                    f"FROM {TASK_TABLE} WHERE task_id=:tid"
                ),
                {"tid": task_id},
            )
        ).one()
        assert row[0] == task_id
        assert row[1] == resource_id
        assert row[2] == fingerprint
        assert row[3] == "1.0.0"
        assert row[4] == "pending"

    await reopened_state.dispose()
    await reopened_index.dispose()


async def test_completed_task_stores_result_json_without_overwriting_catalog(tmp_path, monkeypatch):
    """A completed task stores the parser result as JSON text in result_json.
    Catalog fields are not overwritten by this slice."""
    state_engine, index_engine = _engines(tmp_path)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    factory = async_sessionmaker(state_engine, expire_on_commit=False)
    entry_id = "ce_json_" + "4" * 28
    async with factory() as session:
        session.add(
            models.CatalogEntry(
                entry_id=entry_id,
                content_type="software",
                slug="json-app",
                title="Json App",
            )
        )
        session.add(
            models.CatalogRelease(
                release_id="cr_json",
                entry_id=entry_id,
                slug="1.0",
                title="1.0",
                channel="stable",
            )
        )
        session.add(
            models.CatalogAsset(
                asset_id="ca_json",
                release_id="cr_json",
                slug="asset",
                display_name="app-1.0.zip",
                platform="linux",
                architecture="x64",
                package_type="zip",
            )
        )
        await session.commit()

    result_payload = {
        "platform": "linux",
        "architecture": "x64",
        "language": "unknown",
        "version": "1.0",
        "package_form": "zip",
    }
    task_id = "pt_json_" + "5" * 29
    async with factory() as session:
        session.add(
            models.ParserCandidateTask(
                task_id=task_id,
                resource_id="r_json",
                input_fingerprint="fp_json",
                parser_version="1.0.0",
                status="completed",
                result_json=json.dumps(result_payload),
            )
        )
        await session.commit()

    async with state_engine.connect() as conn:
        task_row = (
            await conn.execute(
                text(f"SELECT status, result_json FROM {TASK_TABLE} WHERE task_id=:tid"),
                {"tid": task_id},
            )
        ).one()
        assert task_row[0] == "completed"
        assert json.loads(task_row[1]) == result_payload

        asset_row = (
            await conn.execute(
                text(
                    "SELECT platform, architecture, package_type "
                    "FROM catalog_assets WHERE asset_id='ca_json'"
                )
            )
        ).one()
        assert asset_row[0] == "linux"
        assert asset_row[1] == "x64"
        assert asset_row[2] == "zip"

    await state_engine.dispose()
    await index_engine.dispose()


async def test_failed_task_stores_error_text(tmp_path, monkeypatch):
    """A failed task records error text and a completion timestamp."""
    from datetime import datetime, timezone

    state_engine, index_engine = _engines(tmp_path)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    factory = async_sessionmaker(state_engine, expire_on_commit=False)
    task_id = "pt_fail_" + "6" * 29
    completed_at = datetime.now(timezone.utc)
    async with factory() as session:
        session.add(
            models.ParserCandidateTask(
                task_id=task_id,
                resource_id="r_fail",
                input_fingerprint="fp_fail",
                parser_version="1.0.0",
                status="failed",
                error_text="parser timed out",
                completed_at=completed_at,
            )
        )
        await session.commit()

    async with state_engine.connect() as conn:
        row = (
            await conn.execute(
                text(f"SELECT status, error_text, completed_at FROM {TASK_TABLE} WHERE task_id=:tid"),
                {"tid": task_id},
            )
        ).one()
        assert row[0] == "failed"
        assert row[1] == "parser timed out"
        assert row[2] is not None

    await state_engine.dispose()
    await index_engine.dispose()
