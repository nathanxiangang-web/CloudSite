"""admin/sync 路由：同步触发与状态。"""
import asyncio

from fastapi import APIRouter

from ...modules.indexing.contracts.public import (
    read_v2_sync_progress,
    toggle_automatic_sync,
)
from ...schemas import SyncInput

router = APIRouter()

_RECENT_PATHS_MAX = 64


@router.post("/api/admin/sync", status_code=202)
async def sync(payload: SyncInput):
    from ... import main as _main

    if _main.manual_sync_task and not _main.manual_sync_task.done():
        return {"status": "already_running"}
    async with _main.StateSession() as session:
        progress = await read_v2_sync_progress(session)
    if progress.get("status") == "running":
        return {"status": "already_running"}
    _main.manual_sync_task = asyncio.create_task(
        _main._run_manual_sync_in_background(payload.full, payload.force),
        name="cloudsite-manual-sync",
    )
    return {"status": "accepted", "message": "同步任务已启动"}


@router.post("/api/admin/sync/cancel")
async def cancel_sync():
    from ... import main as _main
    from ...main import StateSession

    if not _main.manual_sync_task or _main.manual_sync_task.done():
        return {"status": "not_running"}
    _main.manual_sync_task.cancel()
    from ...modules.indexing.infrastructure.status_store import (
        write_v2_sync_progress,
    )

    async with StateSession() as session:
        await write_v2_sync_progress(session, status="cancelled")
        await session.commit()
    return {"status": "cancelled", "message": "同步任务已取消"}


def _recent_paths(progress: dict[str, object]) -> list[str]:
    raw = progress.get("recent_paths")
    if raw is None:
        raw = progress.get("current_path")

    if isinstance(raw, str):
        paths = [raw] if raw else []
    elif isinstance(raw, list):
        paths = [str(item) for item in raw if str(item)]
    else:
        paths = []
    return paths[-_RECENT_PATHS_MAX:]


def _count(progress: dict[str, object], key: str, fallback: str | None = None) -> int:
    value = progress.get(key)
    if value is None and fallback is not None:
        value = progress.get(fallback)
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


@router.get("/api/admin/sync/status")
async def admin_sync_status():
    from ... import main as _main
    from ...main import StateSession

    manual_running = bool(
        _main.manual_sync_task and not _main.manual_sync_task.done()
    )
    async with StateSession() as session:
        progress = await read_v2_sync_progress(session)

    status = str(progress.get("status") or "idle")
    active_workers = _count(progress, "active_workers")
    if status != "running":
        active_workers = 0

    return {
        "engine_version": "v2",
        "manual_sync_running": manual_running,
        "status": status,
        "categories_done": _count(progress, "categories_done"),
        "elapsed_seconds": _count(progress, "elapsed_seconds"),
        "active_workers": active_workers,
        "directories_done": _count(progress, "directories_done", "dirs_done"),
        "known_pending": _count(progress, "known_pending", "dirs_pending"),
        "entries_discovered": _count(
            progress, "entries_discovered", "entries_scanned"
        ),
        "recent_paths": _recent_paths(progress),
    }


@router.post("/api/admin/sync/auto-toggle")
async def toggle_auto_sync():
    from ...main import StateSession

    async with StateSession() as session:
        enabled = await toggle_automatic_sync(session)
        return {"ok": True, "automatic_sync": enabled}
