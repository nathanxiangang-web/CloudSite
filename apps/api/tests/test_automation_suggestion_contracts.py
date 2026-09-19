"""Automation suggestion cross-module contract tests."""

from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import models as legacy_models  # noqa: F401 - register metadata
from cloudsite.modules.catalog.contracts.public import (
    apply_suggestion_new_entry,
    catalog_suggestion_context,
    list_suggestion_catalog_revisions,
)
from cloudsite.modules.catalog.infrastructure.models import (
    CatalogAsset,
    CatalogEntry,
    CatalogLocation,
    CatalogRelease,
)
from cloudsite.modules.resources.contracts.public import resource_queries
from cloudsite.modules.resources.infrastructure.models import Resource
from cloudsite.platform.db import IndexBase, StateBase


async def _engines():
    state_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    index_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    index_factory = async_sessionmaker(index_engine, expire_on_commit=False)
    async with state_engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as connection:
        await connection.run_sync(IndexBase.metadata.create_all)
    return state_engine, index_engine, state_factory, index_factory


async def test_resources_suggestion_query_preserves_active_filter_order_and_type():
    (
        state_engine,
        index_engine,
        _state_factory,
        index_factory,
    ) = await _engines()
    now = datetime(2026, 9, 19, tzinfo=timezone.utc)

    async with index_factory() as session:
        session.add_all(
            [
                Resource(
                    id="r_old",
                    name="old.zip",
                    path="/software/old.zip",
                    parent_id=None,
                    content_type="software",
                    root_mapping_id=1,
                    extension="zip",
                    mime_type="application/zip",
                    size=10,
                    status="active",
                    indexed_at=now - timedelta(minutes=2),
                ),
                Resource(
                    id="r_new",
                    name="new.zip",
                    path="/software/new.zip",
                    parent_id=None,
                    content_type="software",
                    root_mapping_id=1,
                    extension="zip",
                    mime_type="application/zip",
                    size=20,
                    status="active",
                    indexed_at=now - timedelta(minutes=1),
                ),
                Resource(
                    id="r_other",
                    name="other.mp4",
                    path="/video/other.mp4",
                    parent_id=None,
                    content_type="video",
                    root_mapping_id=2,
                    extension="mp4",
                    mime_type="video/mp4",
                    size=30,
                    status="active",
                    indexed_at=now,
                ),
                Resource(
                    id="r_inactive",
                    name="inactive.zip",
                    path="/software/inactive.zip",
                    parent_id=None,
                    content_type="software",
                    root_mapping_id=1,
                    extension="zip",
                    mime_type="application/zip",
                    size=40,
                    status="missing",
                    indexed_at=now - timedelta(minutes=3),
                ),
            ]
        )
        await session.commit()

    async with index_factory() as session:
        rows = await resource_queries(session).list_suggestion_resources(
            content_type="software",
            limit=10,
        )
        assert [row.id for row in rows] == ["r_old", "r_new"]
        assert rows[0].content_type == "software"
        assert rows[0].size == 10

        one = await resource_queries(session).suggestion_resource(
            resource_id="r_old"
        )
        assert one is not None
        assert one.name == "old.zip"
        assert one.indexed_at is not None

    await state_engine.dispose()
    await index_engine.dispose()


async def test_catalog_suggestion_context_hides_orm_and_preserves_duplicate_lookup():
    (
        state_engine,
        index_engine,
        state_factory,
        _index_factory,
    ) = await _engines()

    async with state_factory() as state:
        state.add_all(
            [
                CatalogEntry(
                    entry_id="ce_bound",
                    content_type="software",
                    slug="bound",
                    title="Bound",
                ),
                CatalogRelease(
                    release_id="cr_bound",
                    entry_id="ce_bound",
                    slug="1-0",
                    title="1.0",
                ),
                CatalogAsset(
                    asset_id="ca_bound",
                    release_id="cr_bound",
                    slug="windows-x64",
                    display_name="Tool.zip",
                    platform="windows",
                    architecture="x64",
                    package_type="zip",
                ),
            ]
        )
        await state.flush()
        state.add(
            CatalogLocation(
                location_id="cl_bound",
                asset_id="ca_bound",
                resource_id="r_bound",
            )
        )
        await state.commit()

    async with state_factory() as state:
        bound = await catalog_suggestion_context(
            state,
            resource_id="r_bound",
            resource_name="Tool.zip",
        )
        assert bound.has_location is True
        assert bound.entry_id == "ce_bound"
        assert bound.release_id == "cr_bound"
        assert bound.asset_id == "ca_bound"
        assert bound.asset_platform == "windows"
        assert bound.asset_architecture == "x64"
        assert bound.asset_package_type == "zip"

        duplicate = await catalog_suggestion_context(
            state,
            resource_id="r_new",
            resource_name="Tool.zip",
        )
        assert duplicate.has_location is False
        assert duplicate.duplicate_entry_id == "ce_bound"
        assert duplicate.duplicate_asset_id == "ca_bound"

    await state_engine.dispose()
    await index_engine.dispose()


async def test_catalog_suggestion_command_returns_persistence_neutral_revision_view():
    (
        state_engine,
        index_engine,
        state_factory,
        index_factory,
    ) = await _engines()

    async with state_factory() as state, index_factory() as index:
        mutation = await apply_suggestion_new_entry(
            state,
            index,
            source_file_id="r_missing",
            fields={
                "content_type": "software",
                "slug": "tool",
                "title": "Tool",
                "asset_slug": "tool-file",
                "asset_display_name": "Tool.zip",
            },
            actor="tester",
        )
        await state.commit()

        assert mutation.entry_id is not None
        assert mutation.release_id is not None
        assert mutation.asset_id is not None
        assert mutation.revision_id is not None

    async with state_factory() as state:
        rows, total = await list_suggestion_catalog_revisions(
            state,
            targets=(("entry", mutation.entry_id),),
            limit=20,
            offset=0,
        )
        assert total >= 1
        assert rows
        revision = rows[-1]
        assert revision.target_type == "entry"
        assert revision.target_id == mutation.entry_id
        assert isinstance(revision.before_json, str)
        assert isinstance(revision.after_json, str)

    await state_engine.dispose()
    await index_engine.dispose()
