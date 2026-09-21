"""后台调度任务：定时清理、自动同步与滚动校验。

函数内部通过 cloudsite.main 引用可被测试 monkeypatch 的符号
（log_operation、cleanup_*、StateSession、各种常量与全局计数器），
因此 main.py 必须保留这些符号的 re-export。
"""
import asyncio
import time
from contextlib import suppress

from sqlalchemy import select

from ..models import SystemSetting
from ..modules.indexing.contracts.public import v2_sync_due
from .sync import run_indexing_v2_production, run_rolling_verification_once

SYNC_INTERVAL_OPTIONS = {180, 360, 720, 1440}
ROLLING_VERIFICATION_INTERVAL_SECONDS = 15 * 60
ROLLING_VERIFICATION_BATCH_SIZE = 20


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


async def _run_rolling_verification_job() -> dict:
    """Run one bounded verification pass without letting failures kill Scheduler."""
    from cloudsite.main import log_operation

    try:
        result = await run_rolling_verification_once(
            batch_size=ROLLING_VERIFICATION_BATCH_SIZE,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        with suppress(Exception):
            await log_operation(
                "sync",
                "rolling_verification_failed",
                "滚动校验失败："
                f"{type(exc).__name__}: {str(exc)[:900]}",
                level="ERROR",
            )
        return {
            "status": "failed",
            "roots": [],
            "errors": [f"{type(exc).__name__}: {exc}"],
        }

    roots = result.get("roots", [])
    dirty = sum(int(item.get("dirty", 0) or 0) for item in roots)
    failed = sum(int(item.get("failed", 0) or 0) for item in roots)
    checked = sum(int(item.get("checked", 0) or 0) for item in roots)

    if result.get("status") == "partial" or failed:
        with suppress(Exception):
            await log_operation(
                "sync",
                "rolling_verification_partial",
                f"滚动校验部分完成：checked={checked} dirty={dirty} failed={failed}",
                level="WARNING",
            )
    elif dirty:
        with suppress(Exception):
            await log_operation(
                "sync",
                "rolling_verification_dirty",
                f"滚动校验发现变化：checked={checked} dirty={dirty}",
            )
    return result


async def _run_sync_or_verification_tick(monotonic_now: float) -> str:
    """Run at most one indexing maintenance action for one Scheduler tick.

    Full sync always wins. Rolling verification only runs when automatic sync
    is enabled, full sync is not due, its low-frequency interval elapsed, and
    no manual/scheduled sync task is already active.
    """
    from cloudsite import main

    async with main.StateSession() as session:
        values = await main.get_system_values(session)
        if not values["automatic_sync"]:
            return "disabled"
        full_sync_due = await v2_sync_due(
            session,
            values["sync_interval_minutes"],
        )

    if main.manual_sync_task and not main.manual_sync_task.done():
        return "busy"

    if full_sync_due:
        main.manual_sync_task = asyncio.current_task()
        try:
            result = await run_indexing_v2_production()
            if result.get("status") == "success":
                # A successful full scan refreshed the same per-directory
                # baselines, so avoid immediately verifying them again.
                main._last_rolling_verification_at = time.monotonic()
            return "full_sync"
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await main.log_operation(
                "sync",
                "scheduler_failed",
                f"自动同步调度失败：{type(exc).__name__}: {str(exc)[:900]}",
                level="ERROR",
            )
            return "full_sync_failed"
        finally:
            main.manual_sync_task = None

    if (
        monotonic_now - main._last_rolling_verification_at
        < main.ROLLING_VERIFICATION_INTERVAL_SECONDS
    ):
        return "idle"

    # Advance before execution so Provider failures cannot create a one-minute
    # retry storm. The next bounded pass becomes eligible after 15 minutes.
    main._last_rolling_verification_at = monotonic_now
    main.manual_sync_task = asyncio.current_task()
    try:
        result = await main._run_rolling_verification_job()
        return (
            "verification"
            if result.get("status") != "failed"
            else "verification_failed"
        )
    finally:
        main.manual_sync_task = None


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
        await _run_sync_or_verification_tick(monotonic_now)
