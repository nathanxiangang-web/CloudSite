"""admin/index routes: index summary, folders and sync history."""

from fastapi import APIRouter, HTTPException, Query

from ...modules.indexing.contracts.public import (
    legacy_sync_queries,
    read_v2_sync_progress,
)
from ...modules.resources.contracts.public import resource_queries

router = APIRouter()

def sync_run_dict(row) -> dict:
    """Compatibility serializer for legacy callers and tests."""

    return {
        "id": row.id,
        "sync_type": row.sync_type,
        "status": row.status,
        "folders_scanned": row.folders_scanned,
        "resources_scanned": row.resources_scanned,
        "added_count": row.added_count,
        "updated_count": row.updated_count,
        "removed_count": row.removed_count,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
        "duration_ms": row.duration_ms,
        "error_message": row.error_message,
        "current_path": row.current_path,
        "roots_total": row.roots_total,
        "roots_completed": row.roots_completed,
        "roots_failed": row.roots_failed,
    }



@router.get("/api/admin/index/summary")
async def admin_index_summary():
    from ... import main as _main
    from ...main import IndexSession, StateSession

    async with IndexSession() as index:
        resources = resource_queries(index)
        counts = await resources.admin_index_counts()
        runs = await legacy_sync_queries(index).list_runs(limit=1)
        latest = runs[0] if runs else None

    v2_running = bool(
        _main.manual_sync_task
        and not _main.manual_sync_task.done()
    )
    async with StateSession() as state:
        v2_progress = await read_v2_sync_progress(state)
    v2_status = str(v2_progress.get("status", "idle"))
    latest_sync = None
    if v2_progress or v2_running:
        latest_sync = {
            "id": 0,
            "sync_type": "windowed",
            "status": v2_status if not v2_running else "running",
            "folders_scanned": int(v2_progress.get("categories_done", 0) or 0),
            "resources_scanned": int(v2_progress.get("entries_scanned", 0) or 0),
            "added_count": 0,
            "updated_count": 0,
            "removed_count": 0,
            "started_at": None,
            "finished_at": None,
            "duration_ms": int(v2_progress.get("elapsed_seconds", 0) or 0) * 1000,
            "error_message": "",
            "current_path": str(v2_progress.get("current_path", "") or ""),
            "roots_total": int(v2_progress.get("categories_total", 0) or 0),
            "roots_completed": int(v2_progress.get("categories_done", 0) or 0),
            "roots_failed": 0,
        }
    elif latest is not None:
        # Historical 1.x runs stay readable after the legacy engine is retired.
        latest_sync = latest.to_dict()
    return {
        "folders": counts.folders,
        "resources": counts.resources,
        "syncing": v2_running,
        "latest_sync": latest_sync,
    }

@router.get("/api/admin/index/folders")
async def admin_index_folders():
    from ...main import IndexSession

    async with IndexSession() as index:
        rows = await resource_queries(index).admin_index_folders()
    return {"items": [row.to_dict() for row in rows]}


@router.get("/api/admin/index/folders/{folder_id}")
async def admin_index_folder_detail(folder_id: str):
    from ...main import IndexSession

    async with IndexSession() as index:
        row = await resource_queries(index).admin_index_folder(
            folder_id=folder_id,
        )
    if row is None:
        raise HTTPException(404, "索引目录不存在")
    return row.to_dict()


@router.get("/api/admin/sync-runs")
async def admin_sync_runs(
    limit: int = Query(10, ge=1, le=100),
):
    from ...main import IndexSession

    async with IndexSession() as index:
        rows = await legacy_sync_queries(index).list_runs(limit=limit)
    return {"items": [row.to_dict() for row in rows]}


@router.get("/api/admin/sync-runs/{run_id}/changes")
async def admin_sync_changes(
    run_id: int,
    limit: int = Query(100, ge=1, le=500),
):
    from ...main import IndexSession

    async with IndexSession() as index:
        queries = legacy_sync_queries(index)
        run = await queries.get_run(run_id)
        if run is None:
            raise HTTPException(404, "同步记录不存在")
        rows = await queries.list_recent_changes(
            sync_run_id=run_id,
            limit=limit,
        )
    return {"items": [row.to_dict() for row in rows]}
