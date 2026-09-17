"""CloudSite 115 cloud download submission state: v25->v26 migration tests.

Exercises:
- fresh database initialization reaches v26 and creates cloud_download_tasks
- upgrading an existing v25 state database preserves existing rows and
  creates the new table
- idempotent re-run of init_databases keeps schema at v26
- owner lookup: rows are scoped by user_id and driver_hash is non-unique
  across users
- submitted URLs / cookies are not stored in this table (column allowlist)

All tests use temporary databases only.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from cloudsite import database
from cloudsite.database import StateBase
from cloudsite.migrations import CURRENT_SCHEMA_VERSION, get_state_schema_version, set_state_schema_version


EXPECTED_COLUMNS = {"id", "user_id", "driver_hash", "status", "display_name", "created_at", "updated_at"}


async def test_fresh_init_reaches_v26(tmp_path, monkeypatch):
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    async with state_engine.connect() as conn:
        assert await get_state_schema_version(conn) == CURRENT_SCHEMA_VERSION == 28

        tables = await conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='cloud_download_tasks'"
        )
        assert tables.fetchone() is not None

        cols = await conn.exec_driver_sql("PRAGMA table_info(cloud_download_tasks)")
        col_names = {row[1] for row in cols.fetchall()}
        assert col_names == EXPECTED_COLUMNS

    await state_engine.dispose()
    await index_engine.dispose()


async def test_old_v25_db_upgrades_to_v26_preserving_rows(tmp_path, monkeypatch):
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
        await conn.execute(
            text(
                "INSERT INTO users "
                "(id, username, username_normalized, password_hash, status, role, created_at, updated_at, created_by_admin) "
                "VALUES (101, 'alice', 'alice', 'argon2-fixture', 'active', 'viewer', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0)"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO users "
                "(id, username, username_normalized, password_hash, status, role, created_at, updated_at, created_by_admin) "
                "VALUES (102, 'bob', 'bob', 'argon2-fixture', 'active', 'viewer', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0)"
            )
        )
        await set_state_schema_version(conn, 25)

    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    async with state_engine.connect() as conn:
        assert await get_state_schema_version(conn) == 28

        users = (await conn.execute(text("SELECT COUNT(*) FROM users"))).scalar_one()
        assert users == 2
        alice = (await conn.execute(text("SELECT id, username FROM users WHERE id = 101"))).one()
        assert tuple(alice) == (101, "alice")

        cols = await conn.exec_driver_sql("PRAGMA table_info(cloud_download_tasks)")
        assert {row[1] for row in cols.fetchall()} == EXPECTED_COLUMNS

    await state_engine.dispose()
    await index_engine.dispose()


async def test_v25_to_v26_idempotent(tmp_path, monkeypatch):
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()
    await database.init_databases()

    async with state_engine.connect() as conn:
        assert await get_state_schema_version(conn) == 28
        rows = await conn.exec_driver_sql(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='cloud_download_tasks'"
        )
        assert rows.fetchone()[0] == 1

    await state_engine.dispose()
    await index_engine.dispose()


async def test_cloud_download_task_owner_lookup_and_driver_hash_nonunique(tmp_path, monkeypatch):
    """Owner lookup is keyed by user_id; driver_hash may repeat across users."""
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    async with state_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO users "
                "(id, username, username_normalized, password_hash, status, role, created_at, updated_at, created_by_admin) "
                "VALUES (201, 'owner_a', 'owner_a', 'argon2-fixture', 'active', 'viewer', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0)"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO users "
                "(id, username, username_normalized, password_hash, status, role, created_at, updated_at, created_by_admin) "
                "VALUES (202, 'owner_b', 'owner_b', 'argon2-fixture', 'active', 'viewer', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0)"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO cloud_download_tasks "
                "(id, user_id, driver_hash, status, display_name, created_at, updated_at) "
                "VALUES (1, 201, 'hash-shared', 'pending', 'task-a', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO cloud_download_tasks "
                "(id, user_id, driver_hash, status, display_name, created_at, updated_at) "
                "VALUES (2, 202, 'hash-shared', 'pending', 'task-b', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO cloud_download_tasks "
                "(id, user_id, driver_hash, status, display_name, created_at, updated_at) "
                "VALUES (3, 201, NULL, 'complete', 'task-c', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )

    async with state_engine.connect() as conn:
        owned_by_a = (
            await conn.execute(
                text(
                    "SELECT id, display_name FROM cloud_download_tasks "
                    "WHERE user_id = 201 ORDER BY id"
                )
            )
        ).all()
        assert [(r[0], r[1]) for r in owned_by_a] == [(1, "task-a"), (3, "task-c")]

        owned_by_b = (
            await conn.execute(
                text(
                    "SELECT id, display_name FROM cloud_download_tasks "
                    "WHERE user_id = 202 ORDER BY id"
                )
            )
        ).all()
        assert [(r[0], r[1]) for r in owned_by_b] == [(2, "task-b")]

        shared_hash_count = (
            await conn.execute(
                text("SELECT COUNT(*) FROM cloud_download_tasks WHERE driver_hash = 'hash-shared'")
            )
        ).scalar_one()
        assert shared_hash_count == 2

    await state_engine.dispose()
    await index_engine.dispose()


async def test_cloud_download_tasks_does_not_store_urls_or_credentials(tmp_path, monkeypatch):
    """Acceptance: submitted URLs and cookies must not be persisted in this table."""
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    async with state_engine.connect() as conn:
        cols = await conn.exec_driver_sql("PRAGMA table_info(cloud_download_tasks)")
        col_names = {row[1] for row in cols.fetchall()}
    forbidden = {
        "url", "source_url", "download_url", "submitted_url", "target_url",
        "cookie", "cookies", "cookie_jar", "credentials", "credential",
        "token", "password", "password_ciphertext", "header", "headers",
    }
    assert not (col_names & forbidden), f"forbidden columns present: {col_names & forbidden}"
    assert col_names == EXPECTED_COLUMNS

    await state_engine.dispose()
    await index_engine.dispose()
