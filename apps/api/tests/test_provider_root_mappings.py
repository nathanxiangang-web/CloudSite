"""Providers content-root mapping boundary regression."""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import models  # noqa: F401 - register shared metadata
from cloudsite.modules.providers.application import connection_admin, root_mappings
from cloudsite.modules.providers.contracts.public import (
    ProviderAdminError,
    create_root_mapping,
    delete_root_mapping,
    list_root_mappings,
    save_admin_connection,
    update_root_mapping,
)
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
            "item_count": 1,
            "base_path": "/",
        }

    async def get_path(self, path: str):
        return {
            "name": path.rsplit("/", 1)[-1],
            "is_dir": not path.endswith(".zip"),
        }


async def _store(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)

    monkeypatch.setattr(
        connection_admin,
        "AListClient",
        _FakeAListClient,
    )
    monkeypatch.setattr(
        root_mappings,
        "AListClient",
        _FakeAListClient,
    )

    async with factory() as state:
        await save_admin_connection(
            state,
            base_url="https://alist.example.com",
            username="admin",
            password="secret",
            remember_credentials=True,
        )
    return engine, factory


async def test_root_mapping_lifecycle_and_normalization(monkeypatch):
    engine, factory = await _store(monkeypatch)

    async with factory() as state:
        assert await list_root_mappings(state) == []

        mapping_id = await create_root_mapping(
            state,
            values={
                "content_type": "software",
                "display_name": "软件",
                "alist_path": "//media///",
                "enabled": True,
                "sort_order": 3,
                "connection_id": 1,
            },
        )
        assert mapping_id > 0

    async with factory() as state:
        rows = await list_root_mappings(state)
        assert len(rows) == 1
        assert rows[0]["alist_path"] == "/media"
        assert rows[0]["display_name"] == "软件"

        await update_root_mapping(
            state,
            mapping_id,
            values={
                "content_type": "software",
                "display_name": "软件更新",
                "alist_path": "/media-v2/",
                "enabled": True,
                "sort_order": 1,
                "connection_id": 1,
            },
        )

    async with factory() as state:
        rows = await list_root_mappings(state)
        assert rows[0]["alist_path"] == "/media-v2"
        assert rows[0]["display_name"] == "软件更新"

        with pytest.raises(ProviderAdminError) as duplicate:
            await create_root_mapping(
                state,
                values={
                    "content_type": "video",
                    "display_name": "重复",
                    "alist_path": "/media-v2",
                    "enabled": True,
                    "sort_order": 2,
                    "connection_id": 1,
                },
            )
        assert duplicate.value.status_code == 409
        assert "已存在" in str(duplicate.value)

    async with factory() as state:
        await delete_root_mapping(state, mapping_id)
        assert await list_root_mappings(state) == []

    await engine.dispose()


async def test_root_mapping_rejects_file_target(monkeypatch):
    engine, factory = await _store(monkeypatch)

    async with factory() as state:
        with pytest.raises(ProviderAdminError) as exc_info:
            await create_root_mapping(
                state,
                values={
                    "content_type": "software",
                    "display_name": "文件",
                    "alist_path": "/file.zip",
                    "enabled": True,
                    "sort_order": 0,
                    "connection_id": 1,
                },
            )
        assert exc_info.value.status_code == 400
        assert str(exc_info.value) == "根目录映射必须指向 AList 文件夹"

    await engine.dispose()


async def test_root_mapping_requires_saved_connection():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)

    async with factory() as state:
        with pytest.raises(ProviderAdminError) as exc_info:
            await create_root_mapping(
                state,
                values={
                    "content_type": "software",
                    "display_name": "软件",
                    "alist_path": "/media",
                    "enabled": True,
                    "sort_order": 0,
                    "connection_id": 1,
                },
            )
        assert exc_info.value.status_code == 409
        assert str(exc_info.value) == "请先保存可用的 AList 连接和凭据"

    await engine.dispose()
