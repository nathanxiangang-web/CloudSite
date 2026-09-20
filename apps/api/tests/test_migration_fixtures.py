"""1.0 旧版本迁移 fixture 测试。

验证 init_databases：
1. 自动补齐新列（幂等 ALTER）
2. 保留已有数据
3. 正确设置 schema_version
4. 多次运行不丢失数据

对应 1.0 开发文档第 20、65 节：每条 Migration 可重复启动恢复 + Direct Older Upgrade。
"""
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import database, models  # noqa: F401  — 确保 ORM 模型注册到 metadata
from cloudsite.database import StateBase
from cloudsite.models import AListConnection, Share, SiteSettings, User, utcnow
from cloudsite.migrations import CURRENT_SCHEMA_VERSION, get_state_schema_version


async def _create_populated_state_db(tmp_path):
    """创建一个有数据的 state.db，用于验证 init_databases 数据保留。"""
    state_path = tmp_path / "state.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{state_path}")

    async with engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        now = utcnow()
        session.add(SiteSettings(
            id=1, site_name="TestSite", home_title="Welcome",
            description="Test desc", submission_email="test@example.com",
            default_share_duration="24h",
        ))
        session.add(AListConnection(
            id=1, base_url="https://alist.example", base_path="/",
            username="admin", password_ciphertext="encrypted", enabled=True,
        ))
        session.add(User(
            id=1, username="testuser", username_normalized="testuser",
            password_hash="hash-value", status="active",
            created_at=now, updated_at=now,
        ))
        session.add(Share(
            token="test-share", object_type="resource", object_id="r1",
            title="file.zip", enabled=True, access_mode="code",
            code_version=1, access_count=5, view_count=5, download_count=3,
            created_at=now, updated_at=now,
        ))
        await session.commit()

    await engine.dispose()
    return state_path


async def test_init_databases_preserves_share_data(tmp_path, monkeypatch):
    """init_databases 后 share 数据完整保留。"""
    state_path = await _create_populated_state_db(tmp_path)
    index_path = tmp_path / "index.db"

    state_engine = create_async_engine(f"sqlite+aiosqlite:///{state_path}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{index_path}")
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)

    await database.init_databases()

    async with state_engine.connect() as conn:
        row = (await conn.execute(text(
            "SELECT token, title, access_count, access_mode, code_version, "
            "view_count, download_count FROM shares WHERE token='test-share'"
        ))).fetchone()
        assert row is not None
        assert row[0] == "test-share"
        assert row[1] == "file.zip"
        assert row[2] == 5
        assert row[3] == "code"
        assert row[4] == 1
        assert row[5] == 5
        assert row[6] == 3

    await state_engine.dispose()
    await index_engine.dispose()


async def test_init_databases_preserves_site_settings(tmp_path, monkeypatch):
    """init_databases 后 site_settings 数据完整保留。"""
    state_path = await _create_populated_state_db(tmp_path)
    index_path = tmp_path / "index.db"

    state_engine = create_async_engine(f"sqlite+aiosqlite:///{state_path}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{index_path}")
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)

    await database.init_databases()

    async with state_engine.connect() as conn:
        row = (await conn.execute(text(
            "SELECT site_name, home_title, submission_email, "
            "registration_enabled, default_share_duration FROM site_settings WHERE id=1"
        ))).fetchone()
        assert row[0] == "TestSite"
        assert row[1] == "Welcome"
        assert row[2] == "test@example.com"
        assert row[3] == 1
        assert row[4] == "24h"

    await state_engine.dispose()
    await index_engine.dispose()


async def test_init_databases_preserves_alist_and_user(tmp_path, monkeypatch):
    """init_databases 后 alist_connection 和 user 数据保留。"""
    state_path = await _create_populated_state_db(tmp_path)
    index_path = tmp_path / "index.db"

    state_engine = create_async_engine(f"sqlite+aiosqlite:///{state_path}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{index_path}")
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)

    await database.init_databases()

    async with state_engine.connect() as conn:
        alist = (await conn.execute(text(
            "SELECT base_url, username, provider_type FROM alist_connections WHERE id=1"
        ))).fetchone()
        assert alist[0] == "https://alist.example"
        assert alist[1] == "admin"
        assert alist[2] == "generic_alist"

        user = (await conn.execute(text(
            "SELECT username, status FROM users WHERE id=1"
        ))).fetchone()
        assert user[0] == "testuser"
        assert user[1] == "active"

    await state_engine.dispose()
    await index_engine.dispose()


async def test_migration_sets_schema_version(tmp_path, monkeypatch):
    """有数据的库迁移后 schema_version 正确设置。"""
    state_path = await _create_populated_state_db(tmp_path)
    index_path = tmp_path / "index.db"

    state_engine = create_async_engine(f"sqlite+aiosqlite:///{state_path}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{index_path}")
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)

    await database.init_databases()

    async with state_engine.connect() as conn:
        assert await get_state_schema_version(conn) == CURRENT_SCHEMA_VERSION

    await state_engine.dispose()
    await index_engine.dispose()


async def test_repeated_init_preserves_all_user_data(tmp_path, monkeypatch):
    """多次 init_databases 不丢失用户数据。"""
    state_path = await _create_populated_state_db(tmp_path)
    index_path = tmp_path / "index.db"

    state_engine = create_async_engine(f"sqlite+aiosqlite:///{state_path}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{index_path}")
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)

    await database.init_databases()
    await database.init_databases()
    await database.init_databases()

    async with state_engine.connect() as conn:
        share = (await conn.execute(text(
            "SELECT token, title FROM shares WHERE token='test-share'"
        ))).fetchone()
        assert share is not None
        assert share[1] == "file.zip"

        site = (await conn.execute(text(
            "SELECT site_name FROM site_settings WHERE id=1"
        ))).fetchone()
        assert site[0] == "TestSite"

        user = (await conn.execute(text(
            "SELECT username FROM users WHERE id=1"
        ))).fetchone()
        assert user[0] == "testuser"

        assert await get_state_schema_version(conn) == CURRENT_SCHEMA_VERSION

    await state_engine.dispose()
    await index_engine.dispose()


async def test_share_view_count_synced_from_access_count(tmp_path, monkeypatch):
    """旧 share 的 view_count=0 但 access_count>0 时，view_count 应同步。"""
    state_path = tmp_path / "state.db"
    index_path = tmp_path / "index.db"

    state_engine = create_async_engine(f"sqlite+aiosqlite:///{state_path}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{index_path}")

    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)

    now = utcnow()
    factory = async_sessionmaker(state_engine, expire_on_commit=False)
    async with factory() as session:
        session.add(SiteSettings(id=1))
        session.add(Share(
            token="legacy-view", object_type="resource", object_id="r1",
            title="old.zip", enabled=True, access_mode="code",
            code_version=0, access_count=10, view_count=0, download_count=0,
            created_at=now, updated_at=now,
        ))
        await session.commit()

    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    async with state_engine.connect() as conn:
        row = (await conn.execute(text(
            "SELECT view_count, access_count FROM shares WHERE token='legacy-view'"
        ))).fetchone()
        assert row[0] == 10  # view_count 从 access_count 同步
        assert row[1] == 10

    await state_engine.dispose()
    await index_engine.dispose()
