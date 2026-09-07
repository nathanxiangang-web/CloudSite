"""admin/overview 路由：后台概览面板。"""
from fastapi import APIRouter
from sqlalchemy import desc, func, select

from ...indexer import sync_circuit_status
from ...models import AListConnection, DownloadEvent, Folder, OperationLog, Resource, SyncRun

router = APIRouter()


@router.get("/api/admin/overview")
async def admin_overview():
    from ...main import StateSession, IndexSession

    async with StateSession() as state, IndexSession() as index:
        resource_total = int(await index.scalar(select(func.count()).select_from(Resource).where(Resource.status == "active")) or 0)
        folder_total = int(await index.scalar(select(func.count()).select_from(Folder).where(Folder.status == "active")) or 0)
        failures = int(await state.scalar(select(func.count()).select_from(DownloadEvent).where(DownloadEvent.result == "failed")) or 0)
        connection = await state.get(AListConnection, 1)
        latest_sync = await index.scalar(select(SyncRun).order_by(desc(SyncRun.id)).limit(1))
        logs = list((await state.scalars(select(OperationLog).order_by(desc(OperationLog.id)).limit(6))).all())
        type_counts = {}
        for kind in ("software", "image", "video", "document", "file"):
            type_counts[kind] = int(await index.scalar(select(func.count()).select_from(Resource).where(Resource.content_type == kind, Resource.status == "active")) or 0)
        circuit = await sync_circuit_status()
        return {
            "resources": resource_total,
            "folders": folder_total,
            "download_failures": failures,
            "alist_connected": bool(connection and connection.enabled and connection.last_test_status == "success"),
            "latest_sync": None if not latest_sync else {
                "id": latest_sync.id,
                "status": latest_sync.status,
                "finished_at": latest_sync.finished_at,
                "added": latest_sync.added_count,
                "updated": latest_sync.updated_count,
                "removed": latest_sync.removed_count,
                "folders_scanned": latest_sync.folders_scanned,
                "resources_scanned": latest_sync.resources_scanned,
                "current_path": latest_sync.current_path,
                "roots_total": latest_sync.roots_total,
                "roots_completed": latest_sync.roots_completed,
                "roots_failed": latest_sync.roots_failed,
                "duration_ms": latest_sync.duration_ms,
            },
            "sync_circuit": {
                "open": circuit["open"],
                "until": circuit["until"],
                "reason": circuit["reason"],
            },
            "type_counts": type_counts,
            "logs": [{"level": row.level, "message": row.message, "created_at": row.created_at} for row in logs],
        }