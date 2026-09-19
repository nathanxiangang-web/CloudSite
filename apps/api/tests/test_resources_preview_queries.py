"""Resources preview-query boundary regression tests."""

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.modules.resources.domain.errors import (
    ResourceNotAvailableError,
    ResourceNotFoundError,
)
from cloudsite.modules.resources.infrastructure.models import Resource
from cloudsite.modules.resources.infrastructure.query_repository import (
    SqlAlchemyResourceQueryRepository,
)
from cloudsite.office import office_cache_filename
from cloudsite.platform.db import IndexBase
from cloudsite.preview import preview_capability


async def _factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)
    return engine, factory


async def _seed(factory):
    now = datetime(2026, 9, 19, tzinfo=timezone.utc)
    async with factory() as session:
        session.add_all(
            [
                Resource(
                    id="r_pdf",
                    name="manual.pdf",
                    path="/docs/manual.pdf",
                    parent_id=None,
                    content_type="document",
                    root_mapping_id=1,
                    extension="pdf",
                    mime_type="application/pdf",
                    size=123,
                    modified_at=now,
                    status="active",
                    indexed_at=now,
                ),
                Resource(
                    id="r_other_root",
                    name="other.pdf",
                    path="/other/other.pdf",
                    parent_id=None,
                    content_type="document",
                    root_mapping_id=2,
                    extension="pdf",
                    mime_type="application/pdf",
                    size=456,
                    modified_at=now,
                    status="active",
                    indexed_at=now,
                ),
                Resource(
                    id="r_inactive",
                    name="gone.txt",
                    path="/docs/gone.txt",
                    parent_id=None,
                    content_type="document",
                    root_mapping_id=1,
                    extension="txt",
                    mime_type="text/plain",
                    size=10,
                    modified_at=now,
                    status="missing",
                    indexed_at=now,
                ),
                Resource(
                    id="r_unmapped",
                    name="legacy.txt",
                    path="/legacy.txt",
                    parent_id=None,
                    content_type="document",
                    root_mapping_id=None,
                    extension="txt",
                    mime_type="text/plain",
                    size=10,
                    modified_at=now,
                    status="active",
                    indexed_at=now,
                ),
            ]
        )
        await session.commit()


async def test_preview_resource_returns_internal_dto_compatible_with_preview_helpers():
    engine, factory = await _factory()
    await _seed(factory)

    async with factory() as session:
        repository = SqlAlchemyResourceQueryRepository(session)
        resource = await repository.preview_resource(
            resource_id="r_pdf",
            enabled_root_ids={1},
        )

        assert resource.id == "r_pdf"
        assert resource.path == "/docs/manual.pdf"
        assert resource.root_mapping_id == 1
        assert resource.status == "active"
        assert preview_capability(resource)["preview_type"] == "pdf"
        assert office_cache_filename(resource) == "r_pdf.pdf"

    await engine.dispose()


async def test_preview_resource_preserves_visibility_fail_closed_behavior():
    engine, factory = await _factory()
    await _seed(factory)

    async with factory() as session:
        repository = SqlAlchemyResourceQueryRepository(session)

        with pytest.raises(ResourceNotFoundError):
            await repository.preview_resource(
                resource_id="missing",
                enabled_root_ids={1},
            )

        with pytest.raises(ResourceNotFoundError):
            await repository.preview_resource(
                resource_id="r_inactive",
                enabled_root_ids={1},
            )

        with pytest.raises(ResourceNotAvailableError):
            await repository.preview_resource(
                resource_id="r_other_root",
                enabled_root_ids={1},
            )

        with pytest.raises(ResourceNotAvailableError):
            await repository.preview_resource(
                resource_id="r_unmapped",
                enabled_root_ids={1},
            )

    await engine.dispose()
