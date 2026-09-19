"""Resources download lookup boundary tests."""

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.modules.resources.domain.errors import (
    ResourceInactiveError,
    ResourceNotAvailableError,
    ResourceNotFoundError,
)
from cloudsite.modules.resources.infrastructure.models import Resource
from cloudsite.modules.resources.infrastructure.query_repository import (
    SqlAlchemyResourceQueryRepository,
)
from cloudsite.platform.db import IndexBase


async def _factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)
    return engine, factory


async def _seed(factory):
    now = datetime(2026, 9, 19, tzinfo=timezone.utc)
    async with factory() as session:
        for rid, status, root in [
            ("r_active", "active", 1),
            ("r_missing", "missing", 1),
            ("r_suspected", "suspected_missing", 1),
            ("r_other_root", "active", 2),
            ("r_no_root", "active", None),
        ]:
            session.add(
                Resource(
                    id=rid,
                    name=f"{rid}.zip",
                    path=f"/files/{rid}.zip",
                    parent_id=None,
                    content_type="software",
                    root_mapping_id=root,
                    extension="zip",
                    mime_type="application/zip",
                    size=1,
                    status=status,
                    indexed_at=now,
                )
            )
        await session.commit()


async def test_download_resource_returns_internal_view_for_active_published_resource():
    engine, factory = await _factory()
    await _seed(factory)

    async with factory() as session:
        repository = SqlAlchemyResourceQueryRepository(session)
        resource = await repository.download_resource(
            resource_id="r_active",
            enabled_root_ids={1},
        )
        assert resource.id == "r_active"
        assert resource.path == "/files/r_active.zip"
        assert resource.root_mapping_id == 1
        assert resource.status == "active"

    await engine.dispose()


@pytest.mark.parametrize("resource_id", ["r_missing", "does-not-exist"])
async def test_download_resource_maps_missing_state_to_not_found(resource_id):
    engine, factory = await _factory()
    await _seed(factory)

    async with factory() as session:
        repository = SqlAlchemyResourceQueryRepository(session)
        with pytest.raises(ResourceNotFoundError):
            await repository.download_resource(
                resource_id=resource_id,
                enabled_root_ids={1},
            )

    await engine.dispose()


async def test_download_resource_keeps_non_active_state_distinct():
    engine, factory = await _factory()
    await _seed(factory)

    async with factory() as session:
        repository = SqlAlchemyResourceQueryRepository(session)
        with pytest.raises(ResourceInactiveError):
            await repository.download_resource(
                resource_id="r_suspected",
                enabled_root_ids={1},
            )

    await engine.dispose()


@pytest.mark.parametrize("resource_id", ["r_other_root", "r_no_root"])
async def test_download_resource_fails_closed_outside_publication_scope(resource_id):
    engine, factory = await _factory()
    await _seed(factory)

    async with factory() as session:
        repository = SqlAlchemyResourceQueryRepository(session)
        with pytest.raises(ResourceNotAvailableError):
            await repository.download_resource(
                resource_id=resource_id,
                enabled_root_ids={1},
            )

    await engine.dispose()
