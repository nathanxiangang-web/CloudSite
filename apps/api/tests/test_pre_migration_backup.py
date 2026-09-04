"""1.0 Pre-Migration Backup 测试。

验证 init_databases 在检测到旧 schema_version 时自动创建 state.db 快照。
对应 1.0 开发文档第 21 节：Pre-Migration Backup。
"""
import sqlite3
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import database, models  # noqa: F401
from cloudsite.config import settings
from cloudsite.database import StateBase
from cloudsite.migrations import CURRENT_SCHEMA_VERSION


async def test_no_backup_for_fresh_database(tmp_path, monkeypatch):
    """新库（无 state.db）不创建快照。"""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)

    await database.init_databases()

    backup_dir = tmp_path / ".codex-backups" / "pre-migration"
    assert not backup_dir.exists() or not list(backup_dir.iterdir())

    await state_engine.dispose()
    await index_engine.dispose()


async def test_no_backup_for_current_schema(tmp_path, monkeypatch):
    """已是最新 schema_version 的库不创建快照。"""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)

    # 第一次 init 创建并设置 schema_version
    await database.init_databases()
    await state_engine.dispose()

    # 第二次 init 不应创建快照
    state_engine2 = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    monkeypatch.setattr(database, "state_engine", state_engine2)
    await database.init_databases()

    backup_dir = tmp_path / ".codex-backups" / "pre-migration"
    assert not backup_dir.exists() or not list(backup_dir.iterdir())

    await state_engine2.dispose()
    await index_engine.dispose()


async def test_backup_created_for_old_schema(tmp_path, monkeypatch):
    """旧版本 schema_version 的库创建快照。"""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    state_path = tmp_path / "state.db"

    # 创建一个有数据但 schema_version=0 的旧库
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{state_path}")
    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    await state_engine.dispose()

    # init_databases 应检测到 schema_version=0 并创建快照
    state_engine2 = create_async_engine(f"sqlite+aiosqlite:///{state_path}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    monkeypatch.setattr(database, "state_engine", state_engine2)
    monkeypatch.setattr(database, "index_engine", index_engine)

    await database.init_databases()

    backup_dir = tmp_path / ".codex-backups" / "pre-migration"
    assert backup_dir.exists()
    backups = list(backup_dir.iterdir())
    assert len(backups) >= 1
    # 快照目录中有 state.db
    snapshot = backups[0]
    assert (snapshot / "state.db").exists()
    # 快照是有效的 SQLite 文件
    conn = sqlite3.connect(str(snapshot / "state.db"))
    try:
        result = conn.execute("PRAGMA quick_check(1)").fetchone()
        assert result[0] == "ok"
    finally:
        conn.close()

    await state_engine2.dispose()
    await index_engine.dispose()


async def test_backup_preserves_data(tmp_path, monkeypatch):
    """快照保留了迁移前的数据。"""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    state_path = tmp_path / "state.db"

    # 创建旧库并插入数据
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{state_path}")
    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)

    from cloudsite.models import SiteSettings
    factory = async_sessionmaker(state_engine, expire_on_commit=False)
    async with factory() as session:
        session.add(SiteSettings(id=1, site_name="PreMigration"))
        await session.commit()
    await state_engine.dispose()

    # init_databases 创建快照
    state_engine2 = create_async_engine(f"sqlite+aiosqlite:///{state_path}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    monkeypatch.setattr(database, "state_engine", state_engine2)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    # 快照中的数据应与迁移前一致
    backup_dir = tmp_path / ".codex-backups" / "pre-migration"
    snapshot = list(backup_dir.iterdir())[0]
    conn = sqlite3.connect(str(snapshot / "state.db"))
    try:
        row = conn.execute(
            "SELECT site_name FROM site_settings WHERE id=1"
        ).fetchone()
        assert row[0] == "PreMigration"
    finally:
        conn.close()

    await state_engine2.dispose()
    await index_engine.dispose()
