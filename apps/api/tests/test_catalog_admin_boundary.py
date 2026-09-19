"""Regression coverage for the Catalog admin module boundary."""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.database import IndexBase, StateBase
from cloudsite.models import ContentRootMapping, Resource
from cloudsite.modules.catalog.contracts.public import (
    CatalogDeleteConflict,
    admin_entry_summary_page,
    admin_legacy_entry_detail,
    admin_location_views,
    create_catalog_asset,
    create_catalog_entry,
    delete_catalog_release,
    attach_catalog_location,
)


async def _stores(tmp_path):
    state_engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'state.db'}"
    )
    index_engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'index.db'}"
    )
    state_factory = async_sessionmaker(
        state_engine,
        expire_on_commit=False,
    )
    index_factory = async_sessionmaker(
        index_engine,
        expire_on_commit=False,
    )
    async with state_engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as connection:
        await connection.run_sync(IndexBase.metadata.create_all)
    return state_engine, index_engine, state_factory, index_factory


async def test_admin_facade_projects_entry_and_location(tmp_path):
    (
        state_engine,
        index_engine,
        state_factory,
        index_factory,
    ) = await _stores(tmp_path)

    resource_id = "r_" + "a" * 32
    async with state_factory() as state:
        state.add(
            ContentRootMapping(
                id=1,
                content_type="software",
                display_name="software",
                alist_path="/software",
                enabled=True,
            )
        )
        entry_result = await create_catalog_entry(
            state,
            content_type="software",
            slug="admin-boundary",
            title="Admin Boundary",
        )
        asset_result = await create_catalog_asset(
            state,
            release_id=entry_result.release.release_id,
            slug="windows-amd64",
            display_name="admin-boundary.zip",
        )
        await state.commit()

    async with index_factory() as index:
        index.add(
            Resource(
                id=resource_id,
                name="admin-boundary.zip",
                path="/software/admin-boundary.zip",
                parent_id=None,
                content_type="software",
                root_mapping_id=1,
                extension="zip",
                mime_type="application/zip",
                size=123,
                status="active",
            )
        )
        await index.commit()

    async with state_factory() as state, index_factory() as index:
        await attach_catalog_location(
            state,
            index,
            asset_id=asset_result.asset.asset_id,
            resource_id=resource_id,
            label="primary",
            is_primary=True,
            actor="admin",
        )
        await state.commit()

        page = await admin_entry_summary_page(
            state,
            page=1,
            page_size=20,
        )
        assert page["total"] == 1
        assert page["items"][0]["title"] == "Admin Boundary"

        detail = await admin_legacy_entry_detail(
            state,
            index,
            entry_result.entry.entry_id,
            published_only=False,
        )
        assert detail["entry_id"] == entry_result.entry.entry_id
        assert detail["locations"][0]["available"] is True
        assert detail["locations"][0]["content_type"] == "software"

        locations = await admin_location_views(
            state,
            index,
            asset_result.asset.asset_id,
        )
        assert locations[0]["availability"] == "available"
        assert locations[0]["resource"]["id"] == resource_id

        with pytest.raises(CatalogDeleteConflict):
            await delete_catalog_release(
                state,
                entry_result.release.release_id,
                actor="admin",
            )

    await state_engine.dispose()
    await index_engine.dispose()


async def test_release_delete_without_assets_is_module_owned(tmp_path):
    (
        state_engine,
        index_engine,
        state_factory,
        _,
    ) = await _stores(tmp_path)

    async with state_factory() as state:
        entry_result = await create_catalog_entry(
            state,
            content_type="software",
            slug="deletable-release",
            title="Deletable Release",
        )
        await state.commit()

        await delete_catalog_release(
            state,
            entry_result.release.release_id,
            actor="admin",
        )
        await state.commit()

        assert (
            await state.get(
                type(entry_result.release),
                entry_result.release.release_id,
            )
            is None
        )

    await state_engine.dispose()
    await index_engine.dispose()
