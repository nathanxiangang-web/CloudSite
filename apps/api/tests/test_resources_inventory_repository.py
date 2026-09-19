"""Resources inventory repository tests."""

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.modules.resources.contracts.public import ResourceInventoryRecord
from cloudsite.modules.resources.infrastructure.inventory_repository import (
    SqlAlchemyResourceInventoryRepository,
)
from cloudsite.modules.resources.infrastructure.models import Folder, Resource
from cloudsite.platform.db import IndexBase


async def _factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)
    return engine, factory


async def test_resource_inventory_repository_owns_upsert_list_touch_and_remove():
    engine, factory = await _factory()
    now = datetime(2026, 9, 19, tzinfo=timezone.utc)

    async with factory() as session:
        repository = SqlAlchemyResourceInventoryRepository(session)
        written = await repository.upsert(
            [
                ResourceInventoryRecord(
                    resource_id="f_root",
                    category_id="software",
                    provider_id="generic_alist",
                    path="/software",
                    name="software",
                    is_dir=True,
                    content_type="software",
                    root_mapping_id=1,
                    indexed_at=now,
                ),
                ResourceInventoryRecord(
                    resource_id="r_app",
                    category_id="software",
                    provider_id="generic_alist",
                    path="/software/app.zip",
                    name="app.zip",
                    size=42,
                    is_dir=False,
                    parent_id="f_root",
                    content_type="software",
                    root_mapping_id=1,
                    extension="zip",
                    mime_type="application/zip",
                    indexed_at=now,
                ),
            ]
        )
        assert written == 2

        records = await repository.list_indexed(
            category_id="software",
            provider_id="generic_alist",
        )
        by_id = {record.resource_id: record for record in records}
        assert set(by_id) == {"f_root", "r_app"}
        assert by_id["f_root"].is_dir is True
        assert by_id["r_app"].parent_id == "f_root"
        assert by_id["r_app"].extension == "zip"

        touched = await repository.touch_unchanged(["f_root", "r_app"])
        assert touched == 2

        removed = await repository.remove(["f_root", "r_app"])
        assert removed == 2
        assert await session.get(Folder, "f_root") is None
        assert await session.get(Resource, "r_app") is None

    await engine.dispose()


async def test_resource_inventory_repository_does_not_commit_caller_transaction():
    engine, factory = await _factory()

    async with factory() as session:
        repository = SqlAlchemyResourceInventoryRepository(session)
        await repository.upsert(
            [
                ResourceInventoryRecord(
                    resource_id="r_pending",
                    category_id="software",
                    provider_id="generic_alist",
                    path="/software/pending.zip",
                    name="pending.zip",
                    size=1,
                    content_type="software",
                    root_mapping_id=1,
                )
            ]
        )
        assert await session.get(Resource, "r_pending") is not None
        await session.rollback()
        assert await session.get(Resource, "r_pending") is None

    await engine.dispose()
