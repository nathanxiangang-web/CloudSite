"""X1 v24→v25 迁移测试：多连接命名空间 + Provider 兼容记录。"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from cloudsite import database
from cloudsite.database import IndexBase, StateBase
from cloudsite.models import ContentRootMapping, Folder
from cloudsite.migrations import CURRENT_SCHEMA_VERSION, get_state_schema_version, set_state_schema_version


async def test_fresh_init_reaches_v25(tmp_path, monkeypatch):
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    async with state_engine.connect() as conn:
        assert await get_state_schema_version(conn) == CURRENT_SCHEMA_VERSION == 25

        alist_cols = await conn.exec_driver_sql("PRAGMA table_info(alist_connections)")
        assert "name" in {row[1] for row in alist_cols.fetchall()}

        root_cols = await conn.exec_driver_sql("PRAGMA table_info(content_root_mappings)")
        assert "connection_id" in {row[1] for row in root_cols.fetchall()}

        tables = await conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='provider_compat_records'"
        )
        assert tables.fetchone() is not None

    await state_engine.dispose()
    await index_engine.dispose()


async def test_v24_to_v25_idempotent(tmp_path, monkeypatch):
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()
    await database.init_databases()

    async with state_engine.connect() as conn:
        assert await get_state_schema_version(conn) == 25

    await state_engine.dispose()
    await index_engine.dispose()


async def test_old_v24_db_upgrades_to_v25(tmp_path, monkeypatch):
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
        await set_state_schema_version(conn, 24)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    async with state_engine.connect() as conn:
        assert await get_state_schema_version(conn) == 25
        root_cols = await conn.exec_driver_sql("PRAGMA table_info(content_root_mappings)")
        assert "connection_id" in {row[1] for row in root_cols.fetchall()}

    await state_engine.dispose()
    await index_engine.dispose()


async def test_index_path_uniqueness_relaxed(tmp_path, monkeypatch):
    """验收：folders/resources 路径唯一约束从全局放宽为 (root_mapping_id, path)。"""
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    async with index_engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: [
            sync_conn.execute(Folder.__table__.insert().values(
                id="f1", name="folder1", path="/shared/path", content_type="software", root_mapping_id=1,
            )),
            sync_conn.execute(Folder.__table__.insert().values(
                id="f2", name="folder2", path="/shared/path", content_type="software", root_mapping_id=2,
            )),
        ])
        result = await conn.execute(text("SELECT COUNT(*) FROM folders WHERE path = '/shared/path'"))
        assert result.scalar_one() == 2

    await state_engine.dispose()
    await index_engine.dispose()


async def test_content_root_mapping_connection_id_unique(tmp_path, monkeypatch):
    """验收：content_root_mappings (connection_id, alist_path) 唯一而非 alist_path 全局唯一。"""
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    async with state_engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: [
            sync_conn.execute(ContentRootMapping.__table__.insert().values(
                connection_id=1, content_type="software", display_name="root-a", alist_path="/shared/path",
            )),
            sync_conn.execute(ContentRootMapping.__table__.insert().values(
                connection_id=2, content_type="software", display_name="root-b", alist_path="/shared/path",
            )),
        ])
        result = await conn.execute(text("SELECT COUNT(*) FROM content_root_mappings WHERE alist_path = '/shared/path'"))
        assert result.scalar_one() == 2

    await state_engine.dispose()
    await index_engine.dispose()