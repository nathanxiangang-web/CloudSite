"""admin/overview 路由：后台概览面板。"""

from fastapi import APIRouter

from ...modules.delivery.contracts.public import count_failed_downloads
from ...modules.indexing.contracts.public import (
    legacy_sync_queries,
    read_sync_circuit_status,
)
from ...modules.providers.contracts.public import provider_connected
from ...modules.resources.contracts.public import resource_queries
from ...platform.observability import recent_operation_logs

router = APIRouter()

_CONTENT_TYPES = ("software", "image", "video", "document", "file")


@router.get("/api/admin/overview")
async def admin_overview():
    from ...main import IndexSession, StateSession

    async with StateSession() as state, IndexSession() as index:
        queries = resource_queries(index)
        counts = await queries.admin_index_counts()
        type_counts = await queries.admin_content_type_counts(
            content_types=_CONTENT_TYPES,
        )
        failures = await count_failed_downloads(state)
        alist_connected = await provider_connected(state)
        sync_runs = await legacy_sync_queries(index).list_runs(limit=1)
        latest = sync_runs[0] if sync_runs else None
        circuit = await read_sync_circuit_status(state)
        logs = await recent_operation_logs(state, limit=6)

        return {
            "resources": counts.resources,
            "folders": counts.folders,
            "download_failures": failures,
            "alist_connected": alist_connected,
            "latest_sync": (
                None
                if latest is None
                else {
                    "id": latest.id,
                    "status": latest.status,
                    "finished_at": latest.finished_at,
                    "added": latest.added_count,
                    "updated": latest.updated_count,
                    "removed": latest.removed_count,
                    "folders_scanned": latest.folders_scanned,
                    "resources_scanned": latest.resources_scanned,
                    "current_path": latest.current_path,
                    "roots_total": latest.roots_total,
                    "roots_completed": latest.roots_completed,
                    "roots_failed": latest.roots_failed,
                    "duration_ms": latest.duration_ms,
                }
            ),
            "sync_circuit": {
                "open": circuit["open"],
                "until": circuit["until"],
                "reason": circuit["reason"],
            },
            "type_counts": type_counts,
            "logs": logs,
        }
