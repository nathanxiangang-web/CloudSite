"""手动同步与启动同步任务。

函数内部通过 ``cloudsite.main`` 引用可被测试 monkeypatch 的符号
（StateSession、get_system_values 等）。
"""
import asyncio
import random
from contextlib import suppress

from ..config import settings
from ..modules.indexing.contracts.public import v2_sync_due
from ..modules.indexing.infrastructure.legacy_bridge import (
    run_indexing_v2_production as _run_indexing_v2_production,
)
from ..modules.indexing.infrastructure.production_store import ProductionIndexingStore
from ..modules.resources.infrastructure.inventory_repository import (
    SqlAlchemyResourceInventoryRepository,
)


def _production_indexing_store(session):
    resources = SqlAlchemyResourceInventoryRepository(session)
    return ProductionIndexingStore(resources)


async def run_indexing_v2_production():
    """Compatibility composition entry point for manual/startup sync callers."""
    return await _run_indexing_v2_production(
        store_factory=_production_indexing_store,
    )


async def _run_manual_sync_in_background(full: bool, force: bool) -> None:
    from cloudsite import main

    try:
        await run_indexing_v2_production()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        await main.log_operation("sync", "failed", f"后台同步启动失败：{str(exc)[:1000]}", level="ERROR")
    finally:
        main.manual_sync_task = None


async def _safe_startup_sync():
    from cloudsite import main

    delay = random.uniform(
        settings.sync_startup_delay_min_seconds,
        settings.sync_startup_delay_max_seconds,
    )
    await asyncio.sleep(delay)
    async with main.StateSession() as session:
        values = await main.get_system_values(session)
    if not values["sync_on_startup"]:
        return
    with suppress(Exception):
        await run_indexing_v2_production()