"""Providers admin AList connection boundary regression."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import models  # noqa: F401 - register shared metadata
from cloudsite.alist import AListError
from cloudsite.models import OperationLog
from cloudsite.modules.providers.application import connection_admin
from cloudsite.modules.providers.contracts.public import (
    ProviderAdminError,
    admin_connection_settings,
    browse_admin_directories,
    save_admin_connection,
    test_admin_connection as test_connection,
)
from cloudsite.modules.providers.infrastructure.models import AListConnection
from cloudsite.platform.db import StateBase


class _FakeAListClient:
    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url
        self.username = username
        self.password = password

    async def test(self):
        return {
            "ok": True,
            "message": "AList 连接及根目录访问成功",
            "item_count": 2,
            "base_path": "/home",
        }

    async def list_directories(self, path: str):
        assert path == "/docs"
        return [
            {"name": "A", "modified": "2026-01-01T00:00:00Z"},
            {"name": "B", "modified": None},
        ]


class _FailingAListClient:
    def __init__(self, *_args, **_kwargs):
        pass

    async def test(self):
        raise AListError(
            "登录失败",
            "AL-004",
            status_code=401,
            auth_failed=True,
        )


async def _factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    return engine, factory


async def test_admin_connection_lifecycle(monkeypatch):
    engine, factory = await _factory()
    monkeypatch.setattr(connection_admin, "AListClient", _FakeAListClient)

    async with factory() as state:
        initial = await admin_connection_settings(state)
        assert initial["connection_status"] == "unconfigured"
        assert initial["has_password"] is False

        tested = await test_connection(
            state,
            base_url="https://alist.example.com",
            username="admin",
            password="secret",
        )
        assert tested["base_path"] == "/home"

    async with factory() as state:
        row = await state.get(AListConnection, 1)
        assert row is not None
        assert row.last_test_status == "success"
        assert row.base_path == "/home"

        saved = await save_admin_connection(
            state,
            base_url="https://alist.example.com/",
            username="admin",
            password="secret",
            remember_credentials=True,
        )
        assert saved == {"ok": True, "message": "AList 设置已保存"}

    async with factory() as state:
        settings = await admin_connection_settings(state)
        assert settings["base_url"] == "https://alist.example.com"
        assert settings["username"] == "admin"
        assert settings["enabled"] is True
        assert settings["connection_status"] == "connected"
        assert settings["has_password"] is True

        directories = await browse_admin_directories(state, path="docs/")
        assert directories["path"] == "/docs"
        assert directories["parent_path"] == "/"
        assert [item["path"] for item in directories["items"]] == [
            "/docs/A",
            "/docs/B",
        ]

        logs = list(
            (
                await state.scalars(
                    select(OperationLog)
                    .where(OperationLog.module == "alist")
                    .order_by(OperationLog.id)
                )
            ).all()
        )
        assert [row.action for row in logs] == ["test", "save"]

    await engine.dispose()


async def test_admin_connection_failure_persists_status_and_code(monkeypatch):
    engine, factory = await _factory()
    monkeypatch.setattr(
        connection_admin,
        "AListClient",
        _FailingAListClient,
    )

    async with factory() as state:
        with pytest.raises(ProviderAdminError) as exc_info:
            await test_connection(
                state,
                base_url="https://alist.example.com",
                username="admin",
                password="bad",
            )
        assert exc_info.value.code == "AL-004"
        assert exc_info.value.status_code == 401

    async with factory() as state:
        row = await state.get(AListConnection, 1)
        assert row is not None
        assert row.last_test_status == "failed"
        assert "登录失败" in row.last_test_message

        logs = list(
            (
                await state.scalars(
                    select(OperationLog).where(
                        OperationLog.module == "alist",
                        OperationLog.action == "test",
                    )
                )
            ).all()
        )
        assert len(logs) == 1
        assert logs[0].level == "ERROR"

    await engine.dispose()


async def test_save_requires_password_when_none_is_stored():
    engine, factory = await _factory()

    async with factory() as state:
        with pytest.raises(ProviderAdminError) as exc_info:
            await save_admin_connection(
                state,
                base_url="https://alist.example.com",
                username="admin",
                password="",
                remember_credentials=True,
            )
        assert exc_info.value.status_code == 400
        assert exc_info.value.code is None
        assert str(exc_info.value) == "请输入 AList 密码"

    await engine.dispose()
