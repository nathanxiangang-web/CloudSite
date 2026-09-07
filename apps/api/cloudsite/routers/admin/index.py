"""admin/index 路由：索引摘要、目录列表、同步记录。"""
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc, func, select

from ...models import Folder, Resource, SyncChange, SyncRun
from ...services.resources import folder_dict

router = APIRouter()


def sync_run_dict(row: SyncRun) -> dict:
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
    from ...main import IndexSession

    async with IndexSession() as session:
        latest = await session.scalar(select(SyncRun).order_by(desc(SyncRun.id)).limit(1))
        return {
            "folders": int(await session.scalar(select(func.count()).select_from(Folder).where(Folder.status == "active")) or 0),
            "resources": int(await session.scalar(select(func.count()).select_from(Resource).where(Resource.status == "active")) or 0),
            "latest_sync": sync_run_dict(latest) if latest else None,
            "syncing": bool(latest and latest.status == "running"),
        }


@router.get("/api/admin/index/folders")
async def admin_index_folders():
    from ...main import IndexSession

    async with IndexSession() as session:
        rows = list((await session.scalars(select(Folder).where(Folder.status == "active").order_by(Folder.depth, Folder.path))).all())
        return {"items": [folder_dict(row, include_path=True) for row in rows]}


@router.get("/api/admin/index/folders/{folder_id}")
async def admin_index_folder_detail(folder_id: str):
    from ...main import IndexSession

    async with IndexSession() as session:
        row = await session.get(Folder, folder_id)
        if not row or row.status != "active":
            raise HTTPException(404, "索引目录不存在")
        resources_count = int(await session.scalar(select(func.count()).select_from(Resource).where(Resource.parent_id == row.id, Resource.status == "active")) or 0)
        return {**folder_dict(row, include_path=True), "direct_resource_count": resources_count}


@router.get("/api/admin/sync-runs")
async def admin_sync_runs(limit: int = Query(10, ge=1, le=100)):
    from ...main import IndexSession

    async with IndexSession() as session:
        rows = list((await session.scalars(select(SyncRun).order_by(desc(SyncRun.id)).limit(limit))).all())
        return {"items": [sync_run_dict(row) for row in rows]}


@router.get("/api/admin/sync-runs/{run_id}/changes")
async def admin_sync_changes(run_id: int, limit: int = Query(100, ge=1, le=500)):
    from ...main import IndexSession

    async with IndexSession() as session:
        if not await session.get(SyncRun, run_id):
            raise HTTPException(404, "同步记录不存在")
        rows = list((await session.scalars(select(SyncChange).where(SyncChange.sync_run_id == run_id).order_by(desc(SyncChange.id)).limit(limit))).all())
        return {"items": [{"id": row.id, "object_type": row.object_type, "object_id": row.object_id, "change_type": row.change_type, "old_path": row.old_path, "new_path": row.new_path, "created_at": row.created_at} for row in rows]}