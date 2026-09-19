"""Search S1 module boundary regression."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import models  # noqa: F401 - register shared metadata
from cloudsite.modules.resources.infrastructure.models import Folder, Resource
from cloudsite.modules.search.application import service as search_service
from cloudsite.modules.search.contracts.public import (
    rebuild_public_search_index,
    search_public_resources,
)
from cloudsite.platform.db import IndexBase, StateBase


async def _store():
    state_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    index_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    state_factory = async_sessionmaker(
        state_engine,
        expire_on_commit=False,
    )
    index_factory = async_sessionmaker(
        index_engine,
        expire_on_commit=False,
    )
    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)
        await conn.exec_driver_sql(
            "CREATE VIRTUAL TABLE search_fts USING fts5("
            "object_id UNINDEXED, object_type UNINDEXED, name, "
            "extension, content_type UNINDEXED, description, tags, "
            "breadcrumb_text)"
        )
    return (
        state_engine,
        index_engine,
        state_factory,
        index_factory,
    )


async def test_search_rebuild_and_visibility_boundary():
    (
        state_engine,
        index_engine,
        state_factory,
        index_factory,
    ) = await _store()

    async with index_factory() as index:
        index.add_all(
            [
                Folder(
                    id="f1",
                    name="Software",
                    path="/software",
                    parent_id=None,
                    content_type="software",
                    root_mapping_id=1,
                    depth=0,
                    status="active",
                ),
                Resource(
                    id="r1",
                    name="Tool One.zip",
                    path="/software/Tool One.zip",
                    parent_id="f1",
                    content_type="software",
                    root_mapping_id=1,
                    extension="zip",
                    mime_type="application/zip",
                    size=10,
                    status="active",
                ),
                Resource(
                    id="r2",
                    name="Tool Hidden.zip",
                    path="/hidden/Tool Hidden.zip",
                    parent_id=None,
                    content_type="software",
                    root_mapping_id=2,
                    extension="zip",
                    mime_type="application/zip",
                    size=20,
                    status="active",
                ),
                Resource(
                    id="r3",
                    name="Tool Missing.zip",
                    path="/software/Tool Missing.zip",
                    parent_id="f1",
                    content_type="software",
                    root_mapping_id=1,
                    extension="zip",
                    mime_type="application/zip",
                    size=30,
                    status="missing",
                ),
            ]
        )
        await index.commit()

    async with state_factory() as state, index_factory() as index:
        rebuilt = await rebuild_public_search_index(state, index)
        assert rebuilt.indexed == 3
        assert rebuilt.folders == 1
        assert rebuilt.resources == 2

    async with state_factory() as state:
        dirty = (
            await state.execute(
                text(
                    "SELECT value FROM system_settings "
                    "WHERE key='search_index_dirty'"
                )
            )
        ).scalar_one()
        assert dirty == "false"

    async with index_factory() as index:
        result = await search_public_resources(
            index,
            query="tool",
            resource_type="software",
            object_type="resource",
            page=1,
            page_size=24,
            sort="relevance",
            enabled_root_ids={1},
        )
        assert result["total"] == 1
        assert result["total_pages"] == 1
        assert [item["id"] for item in result["items"]] == ["r1"]
        item = result["items"][0]
        assert item["object_type"] == "resource"
        assert item["match_type"] == "prefix"
        assert item["parent"] == {"id": "f1", "name": "Software"}
        assert item["breadcrumbs"] == [
            {"id": "f1", "name": "Software"}
        ]

        folder_result = await search_public_resources(
            index,
            query="software",
            resource_type=None,
            object_type="folder",
            page=1,
            page_size=24,
            sort="name",
            enabled_root_ids={1},
        )
        assert folder_result["total"] == 1
        assert folder_result["items"][0]["id"] == "f1"
        assert folder_result["items"][0]["match_type"] == "exact"

    await state_engine.dispose()
    await index_engine.dispose()


async def test_failed_rebuild_keeps_dirty_marker(monkeypatch):
    (
        state_engine,
        index_engine,
        state_factory,
        index_factory,
    ) = await _store()

    async def _fail_rebuild(*_args, **_kwargs):
        raise RuntimeError("simulated rebuild failure")

    monkeypatch.setattr(
        search_service,
        "rebuild_search_index",
        _fail_rebuild,
    )

    async with state_factory() as state, index_factory() as index:
        with pytest.raises(RuntimeError, match="rebuild failure"):
            await rebuild_public_search_index(state, index)

    async with state_factory() as state:
        dirty = (
            await state.execute(
                text(
                    "SELECT value FROM system_settings "
                    "WHERE key='search_index_dirty'"
                )
            )
        ).scalar_one()
        assert dirty == "true"

    await state_engine.dispose()
    await index_engine.dispose()
