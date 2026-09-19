"""Regression coverage for removing the unused durable admin-session schema."""

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from cloudsite import database
from cloudsite.database import IndexBase, StateBase
from cloudsite.migrations import CURRENT_SCHEMA_VERSION, get_state_schema_version


async def _table_names(conn) -> set[str]:
    return await conn.run_sync(lambda sync_conn: set(inspect(sync_conn).get_table_names()))


async def test_fresh_init_does_not_keep_admin_sessions(tmp_path, monkeypatch):
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)

    await database.init_databases()

    async with state_engine.connect() as conn:
        assert await get_state_schema_version(conn) == CURRENT_SCHEMA_VERSION
        assert "admin_sessions" not in await _table_names(conn)
        epoch = await conn.execute(
            text("SELECT value FROM system_settings WHERE key='admin_session_epoch'")
        )
        assert epoch.fetchone() is None

    await state_engine.dispose()
    await index_engine.dispose()


async def test_v29_cleanup_drops_abandoned_admin_session_state(tmp_path, monkeypatch):
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")

    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
        await conn.exec_driver_sql(
            "CREATE TABLE admin_sessions("
            "id INTEGER PRIMARY KEY,"
            "session_token_hash VARCHAR(64) NOT NULL UNIQUE,"
            "principal VARCHAR(200) NOT NULL,"
            "authority VARCHAR(100) NOT NULL DEFAULT '',"
            "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
            "last_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
            "expires_at DATETIME NOT NULL,"
            "revoked_at DATETIME,"
            "revocation_reason VARCHAR(40) DEFAULT '',"
            "epoch INTEGER NOT NULL DEFAULT 1,"
            "created_ip_hash VARCHAR(64),"
            "user_agent_hash VARCHAR(64))"
        )
        await conn.execute(
            text(
                "INSERT OR REPLACE INTO system_settings(key, value, value_type, updated_at) "
                "VALUES('schema_version', '29', 'integer', CURRENT_TIMESTAMP)"
            )
        )
        await conn.execute(
            text(
                "INSERT OR REPLACE INTO system_settings(key, value, value_type, updated_at) "
                "VALUES('admin_session_epoch', '7', 'integer', CURRENT_TIMESTAMP)"
            )
        )
    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)

    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    async with state_engine.connect() as conn:
        assert await get_state_schema_version(conn) == CURRENT_SCHEMA_VERSION
        assert "admin_sessions" not in await _table_names(conn)
        epoch = await conn.execute(
            text("SELECT value FROM system_settings WHERE key='admin_session_epoch'")
        )
        assert epoch.fetchone() is None

    await state_engine.dispose()
    await index_engine.dispose()
