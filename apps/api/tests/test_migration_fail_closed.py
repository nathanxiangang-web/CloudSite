"""Runtime proof that a failed state database migration is fail-closed and transaction-safe.

Covers:
1. A migration that performs detectable work (creates a marker table + row) and
   then raises must not commit the marker or advance schema_version.
2. Sentinel data inserted before the migration and the pre-migration backup
   must survive the failure with a quick-check-clean snapshot.
3. After restoring the normal migration chain, a retry must reach
   CURRENT_SCHEMA_VERSION with sentinel data preserved.

All databases are temporary under tmp_path; no production paths are touched.
"""
import sqlite3

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import database, models  # noqa: F401  -- register ORM metadata
from cloudsite.config import settings
from cloudsite.database import StateBase
from cloudsite.migrations import (
    CURRENT_SCHEMA_VERSION,
    Migration,
    get_state_schema_version,
    set_state_schema_version,
)
from cloudsite.models import SiteSettings


SENTINEL_SITE_NAME = "SentinelSurvivor"
MIGRATION_FAILURE_MESSAGE = "test-only migration failure"
MARKER_TABLE = "_test_fail_marker"


async def _create_state_db_with_sentinel(tmp_path):
    """Create state.db with sentinel data at schema_version=1; return (state_path, index_path)."""
    state_path = tmp_path / "state.db"
    index_path = tmp_path / "index.db"

    engine = create_async_engine(f"sqlite+aiosqlite:///{state_path}")
    async with engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(SiteSettings(id=1, site_name=SENTINEL_SITE_NAME))
        await session.commit()

    async with engine.begin() as conn:
        await set_state_schema_version(conn, 1)

    await engine.dispose()
    return state_path, index_path


def _failing_migration_chain():
    """Build a migration chain whose v1->v2 upgrade creates a marker then raises."""

    async def upgrade(conn):
        await conn.exec_driver_sql(
            f"CREATE TABLE {MARKER_TABLE} (id INTEGER PRIMARY KEY, note TEXT NOT NULL)"
        )
        await conn.exec_driver_sql(
            f"INSERT INTO {MARKER_TABLE} (id, note) VALUES (1, 'partial-work-marker')"
        )
        raise RuntimeError(MIGRATION_FAILURE_MESSAGE)

    return [
        Migration(
            id="test_v1_to_v2_fail",
            from_version=1,
            to_version=2,
            upgrade=upgrade,
        )
    ]


def _assert_backup_valid(tmp_path, expected_sentinel):
    """Assert a pre-migration backup exists, is quick-check clean, and preserves sentinel data."""
    backup_dir = tmp_path / ".codex-backups" / "pre-migration"
    assert backup_dir.exists(), "pre-migration backup directory missing"
    backups = sorted(backup_dir.iterdir())
    assert len(backups) >= 1, "no pre-migration snapshot found"
    snapshot = backups[0]
    backup_path = snapshot / "state.db"
    assert backup_path.exists(), "snapshot state.db missing"

    conn = sqlite3.connect(str(backup_path))
    try:
        result = conn.execute("PRAGMA quick_check(1)").fetchone()
        assert result[0] == "ok", "backup quick_check failed"
        row = conn.execute(
            "SELECT site_name FROM site_settings WHERE id=1"
        ).fetchone()
        assert row is not None, "backup lost sentinel row"
        assert row[0] == expected_sentinel, "backup sentinel site_name mismatch"
    finally:
        conn.close()


async def test_failed_migration_rolls_back_marker_and_version(tmp_path, monkeypatch):
    """A failing migration must not commit its marker or advance schema_version."""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    state_path, index_path = await _create_state_db_with_sentinel(tmp_path)

    monkeypatch.setattr(database, "STATE_MIGRATIONS", _failing_migration_chain())

    state_engine = create_async_engine(f"sqlite+aiosqlite:///{state_path}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{index_path}")
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)

    with pytest.raises(RuntimeError, match=MIGRATION_FAILURE_MESSAGE):
        await database.init_databases()

    await state_engine.dispose()
    await index_engine.dispose()

    state_engine = create_async_engine(f"sqlite+aiosqlite:///{state_path}")
    monkeypatch.setattr(database, "state_engine", state_engine)
    try:
        async with state_engine.connect() as conn:
            tables = {
                str(row[0])
                for row in (
                    await conn.exec_driver_sql(
                        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
                    )
                ).fetchall()
            }
            assert MARKER_TABLE not in tables, (
                "marker table committed despite migration failure"
            )
            assert await get_state_schema_version(conn) == 1, (
                "schema_version advanced despite migration failure"
            )
            row = (
                await conn.exec_driver_sql(
                    "SELECT site_name FROM site_settings WHERE id=1"
                )
            ).fetchone()
            assert row is not None, "sentinel row lost during failed migration"
            assert row[0] == SENTINEL_SITE_NAME, "sentinel site_name changed during failed migration"
    finally:
        await state_engine.dispose()


async def test_failed_migration_preserves_sentinel_and_backup(tmp_path, monkeypatch):
    """Sentinel data and a quick-check-clean pre-migration backup must survive the failure."""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    state_path, index_path = await _create_state_db_with_sentinel(tmp_path)

    monkeypatch.setattr(database, "STATE_MIGRATIONS", _failing_migration_chain())

    state_engine = create_async_engine(f"sqlite+aiosqlite:///{state_path}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{index_path}")
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)

    with pytest.raises(RuntimeError, match=MIGRATION_FAILURE_MESSAGE):
        await database.init_databases()

    await state_engine.dispose()
    await index_engine.dispose()

    state_engine = create_async_engine(f"sqlite+aiosqlite:///{state_path}")
    monkeypatch.setattr(database, "state_engine", state_engine)
    try:
        async with state_engine.connect() as conn:
            row = (
                await conn.exec_driver_sql(
                    "SELECT site_name FROM site_settings WHERE id=1"
                )
            ).fetchone()
            assert row is not None, "sentinel row lost after failed migration"
            assert row[0] == SENTINEL_SITE_NAME, "sentinel site_name mismatch after failure"
    finally:
        await state_engine.dispose()

    _assert_backup_valid(tmp_path, SENTINEL_SITE_NAME)


async def test_normal_retry_reaches_current_schema_after_failure(tmp_path, monkeypatch):
    """After a failed migration, restoring the normal chain lets a retry reach CURRENT_SCHEMA_VERSION."""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    state_path, index_path = await _create_state_db_with_sentinel(tmp_path)

    original_migrations = database.STATE_MIGRATIONS
    monkeypatch.setattr(database, "STATE_MIGRATIONS", _failing_migration_chain())

    state_engine = create_async_engine(f"sqlite+aiosqlite:///{state_path}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{index_path}")
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)

    with pytest.raises(RuntimeError, match=MIGRATION_FAILURE_MESSAGE):
        await database.init_databases()

    await state_engine.dispose()
    await index_engine.dispose()

    monkeypatch.setattr(database, "STATE_MIGRATIONS", original_migrations)

    state_engine = create_async_engine(f"sqlite+aiosqlite:///{state_path}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{index_path}")
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)

    await database.init_databases()

    await state_engine.dispose()
    await index_engine.dispose()

    state_engine = create_async_engine(f"sqlite+aiosqlite:///{state_path}")
    monkeypatch.setattr(database, "state_engine", state_engine)
    try:
        async with state_engine.connect() as conn:
            assert await get_state_schema_version(conn) == CURRENT_SCHEMA_VERSION, (
                "retry did not reach CURRENT_SCHEMA_VERSION"
            )
            row = (
                await conn.exec_driver_sql(
                    "SELECT site_name FROM site_settings WHERE id=1"
                )
            ).fetchone()
            assert row is not None, "sentinel row lost after retry"
            assert row[0] == SENTINEL_SITE_NAME, "sentinel site_name mismatch after retry"
    finally:
        await state_engine.dispose()
