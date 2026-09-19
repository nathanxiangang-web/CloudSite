"""Regression coverage for Resources-owned Home inventory queries."""

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.database import IndexBase
from cloudsite.models import Folder, Resource
from cloudsite.modules.resources.contracts.public import resource_queries


async def _store():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(IndexBase.metadata.create_all)
    return engine, factory


async def test_home_inventory_preserves_featured_and_manual_strategies():
    engine, factory = await _store()
    async with factory() as index:
        index.add_all(
            [
                Folder(
                    id="f1",
                    name="root-one",
                    path="/one",
                    content_type="software",
                    root_mapping_id=1,
                    status="active",
                ),
                Folder(
                    id="f2",
                    name="root-two",
                    path="/two",
                    content_type="software",
                    root_mapping_id=2,
                    status="active",
                ),
                Resource(
                    id="r1",
                    name="new-root-one.zip",
                    path="/one/new.zip",
                    content_type="software",
                    root_mapping_id=1,
                    extension="zip",
                    mime_type="application/zip",
                    size=10,
                    status="active",
                    modified_at=datetime(
                        2026, 9, 19, tzinfo=timezone.utc
                    ),
                ),
                Resource(
                    id="r2",
                    name="featured-root-two.zip",
                    path="/two/featured.zip",
                    content_type="software",
                    root_mapping_id=2,
                    extension="zip",
                    mime_type="application/zip",
                    size=20,
                    status="active",
                    modified_at=datetime(
                        2020, 1, 1, tzinfo=timezone.utc
                    ),
                ),
            ]
        )
        await index.commit()

        queries = resource_queries(index)
        featured = await queries.home_inventory(
            enabled_root_ids={1, 2},
            content_types=(
                "software",
                "image",
                "video",
                "document",
                "file",
            ),
            recent_limit=2,
            popular_limit=2,
            popular_strategy="featured",
            featured_resource_ids=["r2"],
            manual_root_order=(1, 2),
        )
        assert [item.id for item in featured.popular] == [
            "r2",
            "r1",
        ]
        assert featured.counts["software"] == 2
        assert featured.resource_count == 2
        assert featured.folder_count == 2
        assert featured.total_size == 30
        assert featured.root_resource_counts == {1: 1, 2: 1}
        assert featured.root_folder_counts == {1: 1, 2: 1}

        manual = await queries.home_inventory(
            enabled_root_ids={1, 2},
            content_types=("software",),
            recent_limit=2,
            popular_limit=2,
            popular_strategy="manual",
            featured_resource_ids=[],
            manual_root_order=(2, 1),
        )
        assert [item.id for item in manual.popular] == [
            "r2",
            "r1",
        ]

    await engine.dispose()
