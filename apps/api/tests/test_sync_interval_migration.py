"""8.1 单元测试：sync_interval_minutes 档位兼容与 Rolling 调度分离。"""
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.database import StateBase
from cloudsite.models import SystemSetting
from cloudsite.schemas import SystemInput


async def _make_state_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    return engine, factory


def test_sync_interval_options_keeps_legacy_180():
    from cloudsite.main import SYNC_INTERVAL_OPTIONS
    assert SYNC_INTERVAL_OPTIONS == {180, 360, 720, 1440}


def test_schema_accepts_all_legacy_intervals():
    for v in (180, 360, 720, 1440):
        assert SystemInput(sync_interval_minutes=v).sync_interval_minutes == v
    with pytest.raises(Exception):
        SystemInput(sync_interval_minutes=60)


def test_no_silent_180_migration_function_exists():
    import cloudsite.main as main
    assert not hasattr(main, "migrate_deprecated_sync_interval")


async def test_get_system_values_preserves_180_and_falls_back_for_invalid(monkeypatch):
    from cloudsite import main
    engine, factory = await _make_state_factory()
    monkeypatch.setattr(main, "StateSession", factory)
    async with factory() as session:
        session.add(SystemSetting(key="sync_interval_minutes", value="180", value_type="string"))
        await session.commit()
        vals = await main.get_system_values(session)
        assert vals["sync_interval_minutes"] == 180
    async with factory() as session:
        row = await session.get(SystemSetting, "sync_interval_minutes")
        row.value = "999"
        await session.commit()
        vals2 = await main.get_system_values(session)
        assert vals2["sync_interval_minutes"] == 360
    await engine.dispose()
