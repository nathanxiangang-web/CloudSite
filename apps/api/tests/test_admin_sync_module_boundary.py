"""Regression tests for the admin sync module boundary."""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.database import StateBase
from cloudsite.models import SystemSetting
from cloudsite.modules.indexing.contracts.public import toggle_automatic_sync


async def _store():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)
    return engine, factory


async def test_toggle_automatic_sync_persists_without_router_orm():
    engine, factory = await _store()
    async with factory() as state:
        assert await toggle_automatic_sync(state) is True
        row = await state.get(SystemSetting, "automatic_sync")
        assert row is not None
        assert row.value == "true"

        assert await toggle_automatic_sync(state) is False
        await state.refresh(row)
        assert row.value == "false"

    await engine.dispose()
