from datetime import datetime, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import search
from cloudsite.database import IndexBase, StateBase
from cloudsite.models import Folder, Resource, SystemSetting


async def test_search_dirty_recovery_rebuilds_from_index_without_alist(monkeypatch):
    state_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    index_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    index_factory = async_sessionmaker(index_engine, expire_on_commit=False)
    async with state_engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as connection:
        await connection.run_sync(IndexBase.metadata.create_all)
        await connection.exec_driver_sql(
            "CREATE VIRTUAL TABLE search_fts USING fts5("
            "object_id UNINDEXED, object_type UNINDEXED, name, extension, "
            "content_type UNINDEXED, description, tags, breadcrumb_text)"
        )
    monkeypatch.setattr(search, "StateSession", state_factory)
    monkeypatch.setattr(search, "IndexSession", index_factory)

    now = datetime(2026, 8, 31, tzinfo=timezone.utc)
    async with state_factory() as session:
        session.add(SystemSetting(key="search_index_dirty", value="true", value_type="boolean"))
        await session.commit()
    async with index_factory() as session:
        session.add_all(
            [
                Folder(
                    id="f-root",
                    name="软件",
                    path="/软件",
                    parent_id=None,
                    content_type="software",
                    root_mapping_id=1,
                    status="active",
                    indexed_at=now,
                ),
                Resource(
                    id="r-file",
                    name="工具.zip",
                    path="/软件/工具.zip",
                    parent_id="f-root",
                    content_type="software",
                    root_mapping_id=1,
                    extension="zip",
                    status="active",
                    indexed_at=now,
                ),
            ]
        )
        await session.commit()

    assert await search.recover_search_index_if_dirty() == 2

    async with index_factory() as session:
        rows = list(
            (
                await session.execute(
                    text("SELECT object_id, object_type FROM search_fts ORDER BY object_type, object_id")
                )
            ).all()
        )
        assert rows == [("f-root", "folder"), ("r-file", "resource")]
    async with state_factory() as session:
        dirty = await session.get(SystemSetting, "search_index_dirty")
        assert dirty.value == "false"

    await state_engine.dispose()
    await index_engine.dispose()


async def test_failed_search_recovery_keeps_dirty_marker(monkeypatch):
    state_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    index_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    index_factory = async_sessionmaker(index_engine, expire_on_commit=False)
    async with state_engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as connection:
        await connection.run_sync(IndexBase.metadata.create_all)
        await connection.exec_driver_sql(
            "CREATE VIRTUAL TABLE search_fts USING fts5("
            "object_id UNINDEXED, object_type UNINDEXED, name, extension, "
            "content_type UNINDEXED, description, tags, breadcrumb_text)"
        )
    monkeypatch.setattr(search, "StateSession", state_factory)
    monkeypatch.setattr(search, "IndexSession", index_factory)
    async with state_factory() as session:
        session.add(SystemSetting(key="search_index_dirty", value="true", value_type="boolean"))
        await session.commit()

    async def fail_rebuild(*_args, **_kwargs):
        raise RuntimeError("simulated interrupted rebuild")

    monkeypatch.setattr(search, "rebuild_search_index", fail_rebuild)
    with pytest.raises(RuntimeError, match="interrupted rebuild"):
        await search.recover_search_index_if_dirty()
    async with state_factory() as session:
        dirty = await session.get(SystemSetting, "search_index_dirty")
        assert dirty.value == "true"

    await state_engine.dispose()
    await index_engine.dispose()
