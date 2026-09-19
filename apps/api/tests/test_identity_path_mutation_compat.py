"""Compatibility test for the legacy Identity -> Resources path-mutation facade."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.database import IndexBase
from cloudsite.identity.service import cascade_rename_descendants
from cloudsite.models import Folder


async def test_legacy_identity_facade_delegates_to_resources_owner():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)

    async with factory() as session:
        session.add(
            Folder(
                id="f_child",
                name="child",
                path="/old/child",
                parent_id=None,
                content_type="software",
                root_mapping_id=1,
                status="active",
            )
        )
        await session.commit()

        result = await cascade_rename_descendants(
            session,
            "f_parent",
            "/old",
            "/new",
        )
        assert result["folders_updated"] == 1
        await session.commit()
        paths = list((await session.scalars(select(Folder.path))).all())
        assert "/new/child" in paths

    await engine.dispose()
