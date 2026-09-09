"""Focused smoke tests for the M2 durable administrator session schema.

Covers the persistence boundary only:
- empty initialization reaches the new schema version and creates admin_sessions
- synthetic v1.0 (schema_version=5) state.db upgrades to v6 with admin_sessions
- repeated initialization is idempotent (no duplicate tables/indexes, version stable)
- only a token hash is persisted; the raw opaque token is never stored
- the model can represent active, expired, revoked, rebind-invalidated, and
  old-epoch sessions

Route and end-to-end authentication tests are deferred.
"""
from datetime import timedelta

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import database, models  # noqa: F401 - register ORM metadata
from cloudsite.database import IndexBase, StateBase
from cloudsite.migrations import (
    CURRENT_SCHEMA_VERSION,
    get_state_schema_version,
    get_index_schema_version,
)

ADMIN_SESSION_TABLE = "admin_sessions"

EXPECTED_COLUMNS = {
    "id",
    "session_token_hash",
    "principal",
    "authority",
    "created_at",
    "last_seen_at",
    "expires_at",
    "revoked_at",
    "revocation_reason",
    "epoch",
    "created_ip_hash",
    "user_agent_hash",
}

EXPECTED_INDEXES = {
    "ix_admin_sessions_session_token_hash",
    "ix_admin_sessions_principal",
    "ix_admin_sessions_expires_at",
    "ix_admin_sessions_revoked_at",
    "ix_admin_sessions_epoch",
}


def _engines(tmp_path):
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    return state_engine, index_engine


async def _table_names(conn) -> set[str]:
    return await conn.run_sync(lambda sync_conn: set(inspect(sync_conn).get_table_names()))


async def _index_names(conn, table: str) -> set[str]:
    return await conn.run_sync(
        lambda sync_conn: {ix["name"] for ix in inspect(sync_conn).get_indexes(table)}
    )


async def _columns(conn, table: str) -> set[str]:
    return await conn.run_sync(
        lambda sync_conn: {column["name"] for column in inspect(sync_conn).get_columns(table)}
    )


async def test_empty_init_creates_admin_sessions_table(tmp_path, monkeypatch):
    """Fresh databases reach the new schema version and contain admin_sessions."""
    state_engine, index_engine = _engines(tmp_path)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)

    await database.init_databases()

    async with state_engine.connect() as conn:
        assert await get_state_schema_version(conn) == CURRENT_SCHEMA_VERSION
        tables = await _table_names(conn)
        assert ADMIN_SESSION_TABLE in tables
        cols = await _columns(conn, ADMIN_SESSION_TABLE)
        assert cols == EXPECTED_COLUMNS, f"column mismatch: {cols ^ EXPECTED_COLUMNS}"
        indexes = await _index_names(conn, ADMIN_SESSION_TABLE)
        assert EXPECTED_INDEXES.issubset(indexes), (
            f"missing indexes: {EXPECTED_INDEXES - indexes}"
        )
    async with index_engine.connect() as conn:
        assert await get_index_schema_version(conn) == CURRENT_SCHEMA_VERSION

    await state_engine.dispose()
    await index_engine.dispose()


async def test_synthetic_v5_upgrades_to_v6(tmp_path, monkeypatch):
    """A synthetic v1.0 (schema_version=5) state.db upgrades to v6 with admin_sessions."""
    state_engine, index_engine = _engines(tmp_path)

    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
        await conn.execute(
            text(
                "INSERT OR REPLACE INTO system_settings(key, value, value_type, updated_at) "
                "VALUES('schema_version', '5', 'integer', CURRENT_TIMESTAMP)"
            )
        )
    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)

    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    async with state_engine.connect() as conn:
        assert await get_state_schema_version(conn) == CURRENT_SCHEMA_VERSION
        tables = await _table_names(conn)
        assert ADMIN_SESSION_TABLE in tables
        count = (
            await conn.execute(text(f"SELECT COUNT(*) FROM {ADMIN_SESSION_TABLE}"))
        ).scalar_one()
        assert count == 0

    await state_engine.dispose()
    await index_engine.dispose()


async def test_repeated_init_is_idempotent(tmp_path, monkeypatch):
    """Re-running initialization does not duplicate tables or indexes and keeps version stable."""
    state_engine, index_engine = _engines(tmp_path)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)

    await database.init_databases()

    async with state_engine.connect() as conn:
        indexes_before = await _index_names(conn, ADMIN_SESSION_TABLE)
        cols_before = await _columns(conn, ADMIN_SESSION_TABLE)

    await database.init_databases()
    await database.init_databases()

    async with state_engine.connect() as conn:
        assert await get_state_schema_version(conn) == CURRENT_SCHEMA_VERSION
        indexes_after = await _index_names(conn, ADMIN_SESSION_TABLE)
        cols_after = await _columns(conn, ADMIN_SESSION_TABLE)
        assert indexes_after == indexes_before, (
            f"index set changed: {indexes_before} -> {indexes_after}"
        )
        assert cols_after == cols_before

    await state_engine.dispose()
    await index_engine.dispose()


async def test_admin_session_stores_token_hash_not_raw_token(tmp_path, monkeypatch):
    """Only the SHA-256 hash of the opaque token is persisted; the raw token is never stored."""
    import hashlib
    import secrets

    state_engine, index_engine = _engines(tmp_path)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    raw_token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    from cloudsite.models import AdminSession, utcnow

    factory = async_sessionmaker(state_engine, expire_on_commit=False)
    async with factory() as session:
        row = AdminSession(
            session_token_hash=token_hash,
            principal="admin",
            authority="role:admin",
            expires_at=utcnow() + timedelta(hours=1),
            epoch=1,
        )
        session.add(row)
        await session.commit()

    async with state_engine.connect() as conn:
        stored_hash = (
            await conn.execute(
                text(f"SELECT session_token_hash FROM {ADMIN_SESSION_TABLE} WHERE principal='admin'")
            )
        ).scalar_one()
        assert stored_hash == token_hash
        assert stored_hash != raw_token
        assert len(stored_hash) == 64
        all_text = (
            await conn.execute(
                text(
                    "SELECT group_concat(session_token_hash || principal || authority, '') "
                    f"FROM {ADMIN_SESSION_TABLE}"
                )
            )
        ).scalar_one()
        assert raw_token not in all_text

    await state_engine.dispose()
    await index_engine.dispose()


async def test_admin_session_represents_lifecycle_states(tmp_path, monkeypatch):
    """The model can represent active, expired, revoked, rebind-invalidated, and old-epoch sessions."""
    import hashlib

    from cloudsite.models import AdminSession, utcnow

    state_engine, index_engine = _engines(tmp_path)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    now = utcnow()
    factory = async_sessionmaker(state_engine, expire_on_commit=False)

    def _hash(label: str) -> str:
        return hashlib.sha256(label.encode()).hexdigest()

    async with factory() as session:
        active = AdminSession(
            session_token_hash=_hash("active"),
            principal="admin",
            authority="role:admin",
            created_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(hours=1),
            epoch=1,
        )
        expired = AdminSession(
            session_token_hash=_hash("expired"),
            principal="admin",
            authority="role:admin",
            created_at=now - timedelta(hours=2),
            last_seen_at=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),
            epoch=1,
        )
        revoked = AdminSession(
            session_token_hash=_hash("revoked"),
            principal="admin",
            authority="role:admin",
            expires_at=now + timedelta(hours=1),
            revoked_at=now,
            revocation_reason="logout",
            epoch=1,
        )
        rebind_invalidated = AdminSession(
            session_token_hash=_hash("rebind"),
            principal="admin",
            authority="role:admin",
            expires_at=now + timedelta(hours=1),
            revoked_at=now,
            revocation_reason="rebind",
            epoch=1,
        )
        old_epoch = AdminSession(
            session_token_hash=_hash("old-epoch"),
            principal="admin",
            authority="role:admin",
            expires_at=now + timedelta(hours=1),
            epoch=0,
        )
        session.add_all([active, expired, revoked, rebind_invalidated, old_epoch])
        await session.commit()

    async with state_engine.connect() as conn:
        total = (
            await conn.execute(text(f"SELECT COUNT(*) FROM {ADMIN_SESSION_TABLE}"))
        ).scalar_one()
        assert total == 5
        active_row = (
            await conn.execute(
                text(
                    f"SELECT revoked_at, expires_at, epoch FROM {ADMIN_SESSION_TABLE} "
                    "WHERE session_token_hash=:h"
                ),
                {"h": _hash("active")},
            )
        ).one()
        assert active_row[0] is None
        assert active_row[2] == 1
        revoked_reason = (
            await conn.execute(
                text(
                    f"SELECT revocation_reason FROM {ADMIN_SESSION_TABLE} "
                    "WHERE session_token_hash=:h"
                ),
                {"h": _hash("rebind")},
            )
        ).scalar_one()
        assert revoked_reason == "rebind"
        epochs = {
            row[0]
            for row in (
                await conn.execute(text(f"SELECT epoch FROM {ADMIN_SESSION_TABLE}"))
            ).all()
        }
        assert epochs == {0, 1}

    await state_engine.dispose()
    await index_engine.dispose()
