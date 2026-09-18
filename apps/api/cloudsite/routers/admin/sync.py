"""admin/sync 路由：同步触发与状态。"""
import asyncio
import json

from fastapi import APIRouter
from sqlalchemy import select

from ...indexer import log_operation, sync_preflight
from ...models import ContentRootMapping, SystemSetting
from ...schemas import PathSyncInput, SyncInput

router = APIRouter()


@router.post("/api/admin/sync", status_code=202)
async def sync(payload: SyncInput):
    from ... import main as _main

    if _main.manual_sync_task and not _main.manual_sync_task.done():
        return {"status": "already_running"}
    preflight = await _main.sync_preflight("manual", payload.force)
    if preflight:
        return preflight
    _main.manual_sync_task = asyncio.create_task(
        _main._run_manual_sync_in_background(payload.full, payload.force),
        name="cloudsite-manual-sync",
    )
    return {"status": "accepted", "message": "同步任务已启动"}


@router.get("/api/admin/sync/status")
async def admin_sync_status():
    from ... import main as _main
    from ...main import StateSession

    manual_running = bool(
        _main.manual_sync_task and not _main.manual_sync_task.done()
    )
    progress = {}
    async with StateSession() as session:
        row = await session.get(SystemSetting, "v2_sync_progress")
        if row and row.value:
            try:
                progress = json.loads(row.value)
            except (ValueError, TypeError):
                progress = {}
    return {
        "engine_version": "v2",
        "manual_sync_running": manual_running,
        "status": progress.get("status", "idle"),
        "categories_done": progress.get("categories_done", 0),
        "categories_total": progress.get("categories_total", 0),
        "elapsed_seconds": progress.get("elapsed_seconds", 0),
    }


@router.post("/api/admin/sync/path", status_code=202)
async def sync_path(payload: PathSyncInput):
    from ...main import StateSession
    from ...sync.path_sync import ManualSyncOrchestrator, validate_paths_under_roots

    async with StateSession() as state_session:
        roots = list((await state_session.scalars(select(ContentRootMapping).where(ContentRootMapping.enabled == True))).all())
    accepted, rejected = validate_paths_under_roots(payload.paths, roots)
    if not accepted:
        return {"status": "invalid_path", "rejected_paths": rejected}
    orchestrator = ManualSyncOrchestrator.instance()
    if not orchestrator.try_reserve():
        return {"status": "already_running"}
    force_refresh_paths = set(accepted) if payload.force_refresh else set()
    asyncio.create_task(orchestrator.start(accepted, force_refresh_paths), name="cloudsite-path-sync")
    await log_operation("sync", "path_sync_triggered", f"手动同步路径: {accepted}, 强制刷新: {payload.force_refresh}")
    return {"status": "accepted", "accepted_paths": accepted, "rejected_paths": rejected}


@router.post("/api/admin/sync/auto-toggle")
async def toggle_auto_sync():
    from ...main import StateSession

    async with StateSession() as session:
        row = await session.get(SystemSetting, "automatic_sync") or SystemSetting(key="automatic_sync")
        current = row.value == "true"
        row.value = "false" if current else "true"
        session.add(row)
        await session.commit()
        return {"ok": True, "automatic_sync": not current}
