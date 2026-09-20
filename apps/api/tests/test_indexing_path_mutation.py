"""Resources ownership tests for descendant path mutation."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.database import IndexBase
from cloudsite.models import Folder, Resource
from cloudsite.modules.resources.infrastructure.inventory_repository import (
    SqlAlchemyResourceInventoryRepository,
)


async def _factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)
    return engine, factory


async def test_resources_repository_rewrites_only_descendant_prefixes():
    engine, factory = await _factory()
    async with factory() as session:
        session.add_all(
            [
                Folder(
                    id="f_root", name="root", path="/a", parent_id=None,
                    content_type="software", root_mapping_id=1, status="active",
                ),
                Folder(
                    id="f_child", name="child", path="/a/child", parent_id="f_root",
                    content_type="software", root_mapping_id=1, status="active",
                ),
                Folder(
                    id="f_other", name="other", path="/a_b/child", parent_id=None,
                    content_type="software", root_mapping_id=1, status="active",
                ),
                Resource(
                    id="r_child", name="file.txt", path="/a/child/file.txt",
                    parent_id="f_child", content_type="software", root_mapping_id=1,
                    status="active", extension="txt", size=1,
                ),
            ]
        )
        await session.commit()

        store = SqlAlchemyResourceInventoryRepository(session)
        result = await store.cascade_descendant_paths("/a", "/renamed")
        assert result == {"folders_updated": 1, "resources_updated": 1}
        await session.commit()

        folder_paths = sorted((await session.scalars(select(Folder.path))).all())
        resource_paths = sorted((await session.scalars(select(Resource.path))).all())
        assert "/renamed/child" in folder_paths
        assert "/a_b/child" in folder_paths
        assert "/renamed/child/file.txt" in resource_paths
    await engine.dispose()


async def test_resources_repository_escapes_percent_and_underscore_in_prefix():
    engine, factory = await _factory()
    async with factory() as session:
        session.add_all(
            [
                Folder(
                    id="f_pct", name="pct", path="/a%/child", parent_id=None,
                    content_type="software", root_mapping_id=1, status="active",
                ),
                Folder(
                    id="f_us", name="us", path="/a_b/child", parent_id=None,
                    content_type="software", root_mapping_id=1, status="active",
                ),
                Folder(
                    id="f_plain", name="plain", path="/axb/child", parent_id=None,
                    content_type="software", root_mapping_id=1, status="active",
                ),
            ]
        )
        await session.commit()

        store = SqlAlchemyResourceInventoryRepository(session)
        pct = await store.cascade_descendant_paths("/a%", "/pct")
        assert pct["folders_updated"] == 1
        us = await store.cascade_descendant_paths("/a_b", "/us")
        assert us["folders_updated"] == 1
        await session.commit()

        paths = sorted((await session.scalars(select(Folder.path))).all())
        assert "/pct/child" in paths
        assert "/us/child" in paths
        assert "/axb/child" in paths
    await engine.dispose()
