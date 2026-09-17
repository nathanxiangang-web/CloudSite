"""Focused tests for legacy global UNIQUE(alist_path) auto-index repair.

Proves that the v24->v25 upgrade and already-v25 startup remove the legacy
single-column UNIQUE(alist_path) auto-index from content_root_mappings and
enforce only composite (connection_id, alist_path) uniqueness. Uses true
legacy table DDL and an already-v25 fixture; no production data is touched.
"""
from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from cloudsite import database
from cloudsite.config import settings
from cloudsite.migrations import (
    CURRENT_SCHEMA_VERSION,
    detect_legacy_alist_path_auto_index,
    get_state_schema_version,
)


LEGACY_V24_DDL = """
CREATE TABLE system_settings (
    key VARCHAR(40) PRIMARY KEY,
    value VARCHAR(200) NOT NULL,
    value_type VARCHAR(20) NOT NULL DEFAULT 'string',
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO system_settings (key, value, value_type) VALUES ('schema_version', '24', 'integer');

CREATE TABLE alist_connections (
    id INTEGER PRIMARY KEY,
    name VARCHAR(100) NOT NULL DEFAULT 'default',
    base_url VARCHAR(500) NOT NULL,
    access_token VARCHAR(500) NOT NULL DEFAULT '',
    base_path VARCHAR(1000) NOT NULL DEFAULT '/',
    provider_type VARCHAR(40) NOT NULL DEFAULT 'generic_alist',
    provider_capability_version INTEGER NOT NULL DEFAULT 1,
    provider_capabilities_json TEXT NOT NULL DEFAULT '',
    capabilities_checked_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE content_root_mappings (
    id INTEGER NOT NULL PRIMARY KEY,
    content_type VARCHAR(40) NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    alist_path VARCHAR(1000) NOT NULL UNIQUE,
    enabled BOOLEAN NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    home_order INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO content_root_mappings (id, content_type, display_name, alist_path, enabled, sort_order, home_order)
VALUES (1, 'software', 'root-a', '/shared/path', 1, 0, 0);
"""

LEGACY_V25_DDL = """
CREATE TABLE system_settings (
    key VARCHAR(40) PRIMARY KEY,
    value VARCHAR(200) NOT NULL,
    value_type VARCHAR(20) NOT NULL DEFAULT 'string',
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO system_settings (key, value, value_type) VALUES ('schema_version', '25', 'integer');

CREATE TABLE alist_connections (
    id INTEGER PRIMARY KEY,
    name VARCHAR(100) NOT NULL DEFAULT 'default',
    base_url VARCHAR(500) NOT NULL,
    access_token VARCHAR(500) NOT NULL DEFAULT '',
    base_path VARCHAR(1000) NOT NULL DEFAULT '/',
    provider_type VARCHAR(40) NOT NULL DEFAULT 'generic_alist',
    provider_capability_version INTEGER NOT NULL DEFAULT 1,
    provider_capabilities_json TEXT NOT NULL DEFAULT '',
    capabilities_checked_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE content_root_mappings (
    id INTEGER NOT NULL PRIMARY KEY,
    connection_id INTEGER NOT NULL DEFAULT 1,
    content_type VARCHAR(40) NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    alist_path VARCHAR(1000) NOT NULL UNIQUE,
    enabled BOOLEAN NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    home_order INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO content_root_mappings (id, connection_id, content_type, display_name, alist_path, enabled, sort_order, home_order)
VALUES (1, 1, 'software', 'root-a', '/shared/path', 1, 0, 0);
"""


def _create_legacy_db(state_path, ddl: str) -> None:
    conn = sqlite3.connect(str(state_path))
    try:
        conn.executescript(ddl)
    finally:
        conn.close()


async def _init_with_engines(tmp_path, monkeypatch):
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    await database.init_databases()
    return state_engine, index_engine


async def test_legacy_v24_column_unique_repaired(tmp_path, monkeypatch):
    """Legacy v24 DB with column-level UNIQUE(alist_path) is repaired on upgrade."""
    _create_legacy_db(tmp_path / "state.db", LEGACY_V24_DDL)
    state_engine, index_engine = await _init_with_engines(tmp_path, monkeypatch)

    async with state_engine.connect() as conn:
        assert await get_state_schema_version(conn) == CURRENT_SCHEMA_VERSION == 29
        legacy = await detect_legacy_alist_path_auto_index(conn)
        assert legacy is None, "legacy auto-index survived v24->v25 upgrade"

    await state_engine.dispose()
    await index_engine.dispose()


async def test_already_v25_with_legacy_auto_index_repaired(tmp_path, monkeypatch):
    """Already-v25 DB with legacy auto-index is repaired on startup."""
    _create_legacy_db(tmp_path / "state.db", LEGACY_V25_DDL)
    state_engine, index_engine = await _init_with_engines(tmp_path, monkeypatch)

    async with state_engine.connect() as conn:
        assert await get_state_schema_version(conn) == CURRENT_SCHEMA_VERSION
        legacy = await detect_legacy_alist_path_auto_index(conn)
        assert legacy is None, "legacy auto-index survived already-v25 repair"

    await state_engine.dispose()
    await index_engine.dispose()


async def test_duplicate_paths_across_connections_after_repair(tmp_path, monkeypatch):
    """After repair, duplicate alist_path under different connection_id values works."""
    _create_legacy_db(tmp_path / "state.db", LEGACY_V24_DDL)
    state_engine, index_engine = await _init_with_engines(tmp_path, monkeypatch)

    async with state_engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO content_root_mappings (connection_id, content_type, display_name, alist_path) "
            "VALUES (2, 'software', 'root-b', '/shared/path')"
        ))
        result = await conn.execute(
            text("SELECT COUNT(*) FROM content_root_mappings WHERE alist_path = '/shared/path'")
        )
        assert result.scalar_one() == 2

    await state_engine.dispose()
    await index_engine.dispose()


async def test_same_connection_duplicate_fails_after_repair(tmp_path, monkeypatch):
    """After repair, same (connection_id, alist_path) duplicate is rejected."""
    _create_legacy_db(tmp_path / "state.db", LEGACY_V24_DDL)
    state_engine, index_engine = await _init_with_engines(tmp_path, monkeypatch)

    async with state_engine.begin() as conn:
        with pytest.raises(Exception):
            await conn.execute(text(
                "INSERT INTO content_root_mappings (connection_id, content_type, display_name, alist_path) "
                "VALUES (1, 'software', 'root-c', '/shared/path')"
            ))

    await state_engine.dispose()
    await index_engine.dispose()


async def test_ids_and_rows_preserved_after_repair(tmp_path, monkeypatch):
    """Repair preserves existing row IDs and column values."""
    state_path = tmp_path / "state.db"
    conn = sqlite3.connect(str(state_path))
    conn.executescript(LEGACY_V24_DDL)
    conn.execute(
        "INSERT INTO content_root_mappings (id, content_type, display_name, alist_path, enabled, sort_order, home_order) "
        "VALUES (5, 'movie', 'root-b', '/movies', 0, 3, 7)"
    )
    conn.commit()
    conn.close()

    state_engine, index_engine = await _init_with_engines(tmp_path, monkeypatch)

    async with state_engine.connect() as conn:
        rows = (
            await conn.exec_driver_sql(
                "SELECT id, content_type, display_name, alist_path, enabled, sort_order, home_order "
                "FROM content_root_mappings ORDER BY id"
            )
        ).fetchall()
        assert (1, "software", "root-a", "/shared/path", 1, 0, 0) in rows
        assert (5, "movie", "root-b", "/movies", 0, 3, 7) in rows

    await state_engine.dispose()
    await index_engine.dispose()


async def test_repeat_startup_preserves_data(tmp_path, monkeypatch):
    """A second startup after repair is a no-op and preserves data."""
    _create_legacy_db(tmp_path / "state.db", LEGACY_V25_DDL)
    state_engine, index_engine = await _init_with_engines(tmp_path, monkeypatch)

    async with state_engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO content_root_mappings (connection_id, content_type, display_name, alist_path) "
            "VALUES (2, 'software', 'root-b', '/shared/path')"
        ))
    await state_engine.dispose()
    await index_engine.dispose()

    state_engine2 = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine2 = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    monkeypatch.setattr(database, "state_engine", state_engine2)
    monkeypatch.setattr(database, "index_engine", index_engine2)
    await database.init_databases()

    async with state_engine2.connect() as conn:
        legacy = await detect_legacy_alist_path_auto_index(conn)
        assert legacy is None, "legacy auto-index reappeared after second startup"
        result = await conn.execute(
            text("SELECT COUNT(*) FROM content_root_mappings WHERE alist_path = '/shared/path'")
        )
        assert result.scalar_one() == 2

    await state_engine2.dispose()
    await index_engine2.dispose()


async def test_pre_repair_backup_created_for_already_v25(tmp_path, monkeypatch):
    """A safe backup is created before repairing an already-v25 database."""
    _create_legacy_db(tmp_path / "state.db", LEGACY_V25_DDL)
    state_engine, index_engine = await _init_with_engines(tmp_path, monkeypatch)

    backup_dir = tmp_path / ".codex-backups" / "pre-migration"
    assert backup_dir.exists(), "pre-migration backup directory missing"
    snapshots = list(backup_dir.iterdir())
    assert len(snapshots) >= 1, "no pre-migration snapshot found"
    backup_path = snapshots[0] / "state.db"
    assert backup_path.exists(), "snapshot state.db missing"

    conn = sqlite3.connect(str(backup_path))
    try:
        result = conn.execute("PRAGMA quick_check(1)").fetchone()
        assert result[0] == "ok", "backup quick_check failed"
        row = conn.execute(
            "SELECT alist_path FROM content_root_mappings WHERE id=1"
        ).fetchone()
        assert row is not None and row[0] == "/shared/path"
    finally:
        conn.close()

    await state_engine.dispose()
    await index_engine.dispose()


async def test_no_backup_when_no_legacy_auto_index(tmp_path, monkeypatch):
    """No pre-migration backup when already-v25 DB has no legacy auto-index."""
    state_engine, index_engine = await _init_with_engines(tmp_path, monkeypatch)
    await state_engine.dispose()
    await index_engine.dispose()

    state_engine2 = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine2 = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    monkeypatch.setattr(database, "state_engine", state_engine2)
    monkeypatch.setattr(database, "index_engine", index_engine2)
    await database.init_databases()

    backup_dir = tmp_path / ".codex-backups" / "pre-migration"
    assert not backup_dir.exists() or not list(backup_dir.iterdir()), (
        "unexpected pre-migration backup for clean v25 DB"
    )

    await state_engine2.dispose()
    await index_engine2.dispose()
