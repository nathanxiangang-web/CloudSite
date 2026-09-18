"""后台调度任务：定时清理与自动同步。

函数内部通过 ``cloudsite.main`` 引用可被测试 monkeypatch 的符号
（log_operation、cleanup_*、StateSession、各种常量与全局计数器），
因此 main.py 必须保留这些符号的 re-export。
"""
import asyncio
import time
from contextlib import suppress

from sqlalchemy import select

from ..models import SystemSetting
from ..modules.indexing.infrastructure.indexing_engine import use_indexing_v2
from ..modules.indexing.infrastructure.legacy_bridge import run_indexing_v2_production

SYNC_INTERVAL_OPTIONS = {180, 360, 720, 1440}


async def get_system_values(session) -> dict:
    rows = list((await session.scalars(select(SystemSetting))).all())
    values = {row.key: row.value for row in rows}
    interval = int(values.get("sync_interval_minutes", "360"))
    return {
        "automatic_sync": values.get("automatic_sync", "false") == "true",
        "sync_interval_minutes": interval if interval in SYNC_INTERVAL_OPTIONS else 360,
        "sync_on_startup": values.get("sync_on_startup", "false") == "true",
    }


async def _run_cleanup_job(action: str, label: str, cleanup) -> None:
    from cloudsite.main import log_operation

    try:
        deleted = await cleanup()
        await log_operation(
            "maintenance",
            action,
            f"{label}完成：清理 {deleted} 条过期记录",
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        with suppress(Exception):
            await log_operation(
                "maintenance",
                f"{action}_failed",
                f"{label}失败：{type(exc).__name__}: {str(exc)[:900]}",
                level="ERROR",
            )


async def scheduler_loop() -> None:
    from cloudsite import main

    while True:
        await asyncio.sleep(60)
        monotonic_now = time.monotonic()
        if monotonic_now - main._last_session_cleanup_at >= main.SESSION_CLEANUP_SECONDS:
            main._last_session_cleanup_at = monotonic_now
            await main._run_cleanup_job(
                "session_cleanup",
                "Session 清理",
                main.cleanup_expired_user_sessions,
            )
        if monotonic_now - main._last_rate_limit_cleanup_at >= main.DOWNLOAD_RATE_CLEANUP_SECONDS:
            main._last_rate_limit_cleanup_at = monotonic_now
            await main._run_cleanup_job(
                "download_rate_cleanup",
                "下载限流清理",
                main.cleanup_download_rate_limits,
            )
        if monotonic_now - main._last_share_cleanup_at >= main.SHARE_CLEANUP_SECONDS:
            main._last_share_cleanup_at = monotonic_now
            await main._run_cleanup_job("share_cleanup", "分享清理", main.cleanup_terminal_shares)
            await main._run_cleanup_job("share_verify_attempt_cleanup", "分享验证码状态清理", main.cleanup_share_verify_attempts)
        async with main.StateSession() as session:
            values = await main.get_system_values(session)
        if not values["automatic_sync"]:
            continue
        try:
            if use_indexing_v2():
                await run_indexing_v2_production()
            elif await main.migrate_existing_index_to_rolling():
                await main.run_due_rolling_window()
            elif await main.automatic_sync_due(values["sync_interval_minutes"]):
                # Freeze the existing first-index bootstrap path.  Rolling 1.1
                # is enabled only after this legacy full sync succeeds.
                await main.run_sync("scheduled")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await main.log_operation(
                "sync",
                "scheduler_failed",
                f"自动同步调度失败：{type(exc).__name__}: {str(exc)[:900]}",
                level="ERROR",
            )