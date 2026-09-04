"""Schema version migration tests.

验证 init_databases 记录显式 schema_version、幂等、旧库（无 schema_version）升级到当前版本。
"""
from sqlalchemy.ext.asyncio import create_async_engine

from cloudsite import database
from cloudsite.database import IndexBase, StateBase
from cloudsite.migrations import (
    CURRENT_SCHEMA_VERSION,
    get_index_schema_version,
    get_state_schema_version,
)


def _engines(tmp_path):
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    return state_engine, index_engine


async def test_init_databases_records_schema_version(tmp_path, monkeypatch):
    state_engine, index_engine = _engines(tmp_path)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    async with state_engine.connect() as conn:
        assert await get_state_schema_version(conn) == CURRENT_SCHEMA_VERSION
    async with index_engine.connect() as conn:
        assert await get_index_schema_version(conn) == CURRENT_SCHEMA_VERSION

    await state_engine.dispose()
    await index_engine.dispose()


async def test_init_databases_is_idempotent(tmp_path, monkeypatch):
    state_engine, index_engine = _engines(tmp_path)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)

    await database.init_databases()
    await database.init_databases()  # 第二次：应无错且版本不变

    async with state_engine.connect() as conn:
        assert await get_state_schema_version(conn) == CURRENT_SCHEMA_VERSION
    async with index_engine.connect() as conn:
        assert await get_index_schema_version(conn) == CURRENT_SCHEMA_VERSION

    await state_engine.dispose()
    await index_engine.dispose()


async def test_old_db_without_schema_version_upgrades(tmp_path, monkeypatch):
    state_engine, index_engine = _engines(tmp_path)
    # 模拟旧库：建表但不记录 schema_version
    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)

    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    async with state_engine.connect() as conn:
        assert await get_state_schema_version(conn) == CURRENT_SCHEMA_VERSION
    async with index_engine.connect() as conn:
        assert await get_index_schema_version(conn) == CURRENT_SCHEMA_VERSION

    await state_engine.dispose()
    await index_engine.dispose()
