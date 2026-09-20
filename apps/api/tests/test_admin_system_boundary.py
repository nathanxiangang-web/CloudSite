"""Regression coverage for the admin System boundary."""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.database import StateBase
from cloudsite.models import OperationLog, SystemSetting
from cloudsite.platform.observability import count_operation_logs
from cloudsite.platform.settings import (
    read_admin_system_settings,
    save_admin_system_settings,
)


async def _store():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)
    return engine, factory


async def test_admin_system_settings_round_trip_without_router_orm():
    engine, factory = await _store()
    async with factory() as state:
        initial = await read_admin_system_settings(state)
        assert initial == {
            "automatic_sync": False,
            "sync_interval_minutes": 360,
            "sync_on_startup": False,
            "initial_index_completed_at": None,
        }

        await save_admin_system_settings(
            state,
            values={
                "automatic_sync": True,
                "sync_interval_minutes": 720,
                "sync_on_startup": True,
            },
        )
        state.add(
            SystemSetting(
                key="initial_index_completed_at",
                value="2026-09-19T00:00:00+00:00",
            )
        )
        state.add(
            OperationLog(
                module="system",
                action="test",
                message="test log",
            )
        )
        await state.commit()

        values = await read_admin_system_settings(state)
        assert values["automatic_sync"] is True
        assert values["sync_interval_minutes"] == 720
        assert values["sync_on_startup"] is True
        assert values["initial_index_completed_at"] == (
            "2026-09-19T00:00:00+00:00"
        )
        assert await count_operation_logs(state) == 1

    await engine.dispose()
