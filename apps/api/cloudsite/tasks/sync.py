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
from ..modules.search.contracts.public import rebuild_public_search_index
from ..platform.db import index_session, state_session


def _production_indexing_store(session):
    resources = SqlAlchemyResourceInventoryRepository(session)
    return ProductionIndexingStore(resources)


async def run_indexing_v2_production():
    """Run indexing and refresh public search from the committed inventory."""
    result = await _run_indexing_v2_production(
        store_factory=_production_indexing_store,
    )
    if result.get("status") in {"success", "partial"}:
        async with state_session() as state, index_session() as index:
            rebuilt = await rebuild_public_search_index(state, index)
        result = {
            **result,
            "search_indexed": rebuilt.indexed,
        }
    return result


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
        if not await v2_sync_due(
            session,
            values["sync_interval_minutes"],
        ):
            return
    if main.manual_sync_task and not main.manual_sync_task.done():
        return
    with suppress(Exception):
        await run_indexing_v2_production()
