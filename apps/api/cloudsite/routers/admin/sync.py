"""admin/sync 路由：同步触发与状态。"""
import asyncio
from fastapi import APIRouter
from ...modules.indexing.contracts.public import (
    read_v2_sync_progress,
    toggle_automatic_sync,
)
from ...schemas import SyncInput

router = APIRouter()


@router.post("/api/admin/sync", status_code=202)
async def sync(payload: SyncInput):
    from ... import main as _main

    if _main.manual_sync_task and not _main.manual_sync_task.done():
        return {"status": "already_running"}
    _main.manual_sync_task = asyncio.create_task(
        _main._run_manual_sync_in_background(payload.full, payload.force),
        name="cloudsite-manual-sync",
    )
    return {"status": "accepted", "message": "同步任务已启动"}


@router.post("/api/admin/sync/cancel")
async def cancel_sync():
    from ... import main as _main

    if not _main.manual_sync_task or _main.manual_sync_task.done():
        return {"status": "not_running"}
    _main.manual_sync_task.cancel()
    return {"status": "cancelled", "message": "同步任务已取消"}


@router.get("/api/admin/sync/status")
async def admin_sync_status():
    from ... import main as _main
    from ...main import StateSession

    manual_running = bool(
        _main.manual_sync_task and not _main.manual_sync_task.done()
    )
    async with StateSession() as session:
        progress = await read_v2_sync_progress(session)
    return {
        "engine_version": "v2",
        "manual_sync_running": manual_running,
        "status": progress.get("status", "idle"),
        "categories_done": progress.get("categories_done", 0),
        "categories_total": progress.get("categories_total", 0),
        "elapsed_seconds": progress.get("elapsed_seconds", 0),
        "current_path": progress.get("current_path", ""),
        "entries_scanned": progress.get("entries_scanned", 0),
    }



@router.post("/api/admin/sync/auto-toggle")
async def toggle_auto_sync():
    from ...main import StateSession

    async with StateSession() as session:
        enabled = await toggle_automatic_sync(session)
        return {"ok": True, "automatic_sync": enabled}
