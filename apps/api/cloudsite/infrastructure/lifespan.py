"""应用生命周期管理：启动初始化与优雅关闭。

lifespan 内部通过 ``cloudsite.main`` 引用可被测试 monkeypatch 的符号，
因此 main.py 必须保留这些符号的 re-export。
"""
import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from ..models import SiteSettings
from ..admin_auth import ensure_setup_compatible, get_setup_completed
from .security import validate_production_secrets


@asynccontextmanager
async def lifespan(_: FastAPI):
    from cloudsite import main

    main.validate_production_secrets()
    main.validate_database_files()
    main.backup_stable_id_databases()
    await main.init_databases()
    main.validate_database_files()
    await main.recover_search_index_if_dirty()
    await main.recover_interrupted_sync_runs()
    await main.migrate_stable_resource_ids()
    await main.recover_rolling_state()
    await main.migrate_existing_index_to_rolling()
    if await main.resolve_rolling_mode() == "INDEX_RECOVERY_REQUIRED":
        await main.prepare_index_recovery()
    async with main.StateSession() as session:
        if not await session.get(SiteSettings, 1):
            session.add(SiteSettings(id=1))
        await ensure_setup_compatible(session)
        await session.commit()
        values = await main.get_system_values(session)
    main.scheduler_task = asyncio.create_task(main.scheduler_loop())
    if values["sync_on_startup"]:
        asyncio.create_task(main._safe_startup_sync())
    yield
    if main.scheduler_task:
        main.scheduler_task.cancel()
        with suppress(asyncio.CancelledError):
            await main.scheduler_task
    if main.manual_sync_task and not main.manual_sync_task.done():
        main.manual_sync_task.cancel()
        with suppress(asyncio.CancelledError):
            await main.manual_sync_task