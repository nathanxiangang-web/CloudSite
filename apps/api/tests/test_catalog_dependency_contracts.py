"""Catalog cross-module contract boundary tests."""

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import models as legacy_models  # noqa: F401 - register metadata
from cloudsite.modules.providers.contracts.public import enabled_root_ids
from cloudsite.modules.providers.infrastructure.models import ContentRootMapping
from cloudsite.modules.resources.contracts.public import resource_queries
from cloudsite.modules.resources.infrastructure.models import Resource
from cloudsite.platform.db import IndexBase, StateBase


async def test_provider_contract_returns_only_enabled_root_ids():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)

    async with factory() as session:
        session.add_all(
            [
                ContentRootMapping(
                    id=11,
                    connection_id=1,
                    content_type="software",
                    display_name="Enabled",
                    alist_path="/enabled",
                    enabled=True,
                ),
                ContentRootMapping(
                    id=12,
                    connection_id=1,
                    content_type="software",
                    display_name="Disabled",
                    alist_path="/disabled",
                    enabled=False,
                ),
            ]
        )
        await session.commit()

    async with factory() as session:
        assert await enabled_root_ids(session) == {11}

    await engine.dispose()


async def test_resources_contract_returns_catalog_resource_snapshot():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)

    now = datetime(2026, 9, 19, tzinfo=timezone.utc)
    async with factory() as session:
        session.add(
            Resource(
                id="r_catalog",
                name="pkg.zip",
                path="/software/pkg.zip",
                parent_id=None,
                content_type="software",
                root_mapping_id=7,
                extension="zip",
                mime_type="application/zip",
                size=10,
                status="suspected_missing",
                indexed_at=now,
            )
        )
        await session.commit()

    async with factory() as session:
        view = await resource_queries(session).catalog_resource(
            resource_id="r_catalog"
        )
        assert view is not None
        assert view.id == "r_catalog"
        assert view.status == "suspected_missing"
        assert view.root_mapping_id == 7
        assert view.content_type == "software"

        assert (
            await resource_queries(session).catalog_resource(
                resource_id="missing"
            )
            is None
        )

    await engine.dispose()
