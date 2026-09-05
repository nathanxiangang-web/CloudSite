"""投稿与通知模块测试：迁移幂等、URL 校验、schema 完整性。

覆盖 TEST-001 中投稿、通知、迁移的最低测试集。
"""
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from cloudsite import models  # noqa: F401  注册所有表到 metadata
from cloudsite.database import StateBase
from cloudsite.migrations import (
    STATE_MIGRATIONS,
    get_state_schema_version,
    run_migrations,
    set_state_schema_version,
    state_v1_to_v2_upgrade,
)


async def test_state_v1_to_v2_creates_tables(tmp_path):
    """v1→v2 迁移创建 submissions 和 notifications 表。"""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
        await set_state_schema_version(conn, 1)
        await state_v1_to_v2_upgrade(conn)
        tables = await conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('submissions','notifications')"
        )
        names = {row[0] for row in tables.fetchall()}
        assert "submissions" in names
        assert "notifications" in names
    await engine.dispose()


async def test_state_v1_to_v2_is_idempotent(tmp_path):
    """v1→v2 迁移幂等：重复执行不报错。"""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
        await state_v1_to_v2_upgrade(conn)
        await state_v1_to_v2_upgrade(conn)
    await engine.dispose()


async def test_run_migrations_advances_v1_to_v2(tmp_path):
    """run_migrations 将 v1 库升级到 v2 并记录已应用迁移。"""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
        await set_state_schema_version(conn, 1)
        final, applied = await run_migrations(
            conn, STATE_MIGRATIONS, get_state_schema_version, set_state_schema_version
        )
        assert final == 2
        assert applied == ["state_v1_to_v2"]
    await engine.dispose()


async def test_run_migrations_skips_when_already_v2(tmp_path):
    """已是 v2 的库不重复执行迁移。"""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
        await set_state_schema_version(conn, 2)
        final, applied = await run_migrations(
            conn, STATE_MIGRATIONS, get_state_schema_version, set_state_schema_version
        )
        assert final == 2
        assert applied == []
    await engine.dispose()


def test_validate_optional_http_url_rejects_javascript():
    """投稿 URL 校验拒绝 javascript: scheme。"""
    from fastapi import HTTPException
    from cloudsite.main import validate_optional_http_url
    with pytest.raises(HTTPException) as exc:
        validate_optional_http_url("javascript:alert(1)", "测试")
    assert exc.value.status_code == 400


def test_validate_optional_http_url_rejects_data_scheme():
    from fastapi import HTTPException
    from cloudsite.main import validate_optional_http_url
    with pytest.raises(HTTPException):
        validate_optional_http_url("data:text/html,<script>", "测试")


def test_validate_optional_http_url_rejects_file_scheme():
    from fastapi import HTTPException
    from cloudsite.main import validate_optional_http_url
    with pytest.raises(HTTPException):
        validate_optional_http_url("file:///etc/passwd", "测试")


def test_validate_optional_http_url_accepts_https():
    from cloudsite.main import validate_optional_http_url
    assert validate_optional_http_url("https://example.com/file.zip", "测试") == "https://example.com/file.zip"


def test_validate_optional_http_url_accepts_http():
    from cloudsite.main import validate_optional_http_url
    assert validate_optional_http_url("http://example.com/file.zip", "测试") == "http://example.com/file.zip"


def test_validate_optional_http_url_accepts_empty_and_whitespace():
    from cloudsite.main import validate_optional_http_url
    assert validate_optional_http_url("", "测试") == ""
    assert validate_optional_http_url("   ", "测试") == ""


def test_validate_optional_http_url_rejects_no_netloc():
    from fastapi import HTTPException
    from cloudsite.main import validate_optional_http_url
    with pytest.raises(HTTPException):
        validate_optional_http_url("https://", "测试")
