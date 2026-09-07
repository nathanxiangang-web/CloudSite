"""手动同步与启动同步任务。

函数内部通过 ``cloudsite.main`` 引用可被测试 monkeypatch 的符号
（rolling_enabled、run_sync、StateSession、get_system_values 等）。
"""
import asyncio
import random
from contextlib import suppress

from ..config import settings


async def _run_manual_sync_in_background(full: bool, force: bool) -> None:
    from cloudsite import main

    try:
        if await main.rolling_enabled():
            await main.run_due_rolling_window(manual=True)
        else:
            result = await main.run_sync("manual", full, force)
            if result.get("status") == "success":
                # The completed first index remains authoritative even if the
                # follow-up migration is temporarily unavailable.  The normal
                # scheduler retries this idempotent migration later.
                with suppress(Exception):
                    await main.migrate_existing_index_to_rolling()
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
        if await main.migrate_existing_index_to_rolling():
            await main.run_due_rolling_window()
        elif await main.automatic_sync_due(values["sync_interval_minutes"]):
            await main.run_sync("startup")