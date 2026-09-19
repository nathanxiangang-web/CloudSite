"""admin/overview route: compose module-owned dashboard reads."""

from fastapi import APIRouter

from ...indexer import sync_circuit_status
from ...modules.delivery.contracts.public import failed_download_count
from ...modules.indexing.contracts.public import legacy_sync_queries
from ...modules.providers.contracts.public import (
    admin_connection_settings,
)
from ...modules.resources.contracts.public import resource_queries
from ...platform.observability import recent_operation_logs

router = APIRouter()


@router.get("/api/admin/overview")
async def admin_overview():
    from ...main import IndexSession, StateSession

    async with StateSession() as state, IndexSession() as index:
        inventory = await resource_queries(
            index
        ).admin_overview_inventory()
        failures = await failed_download_count(state)
        connection = await admin_connection_settings(state)
        runs = await legacy_sync_queries(index).list_runs(limit=1)
        latest_sync = runs[0] if runs else None
        logs = await recent_operation_logs(state, limit=6)

    circuit = await sync_circuit_status()
    return {
        "resources": inventory.resources,
        "folders": inventory.folders,
        "download_failures": failures,
        "alist_connected": (
            connection.get("connection_status") == "connected"
        ),
        "latest_sync": (
            None
            if latest_sync is None
            else {
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
            }
        ),
        "sync_circuit": {
            "open": circuit["open"],
            "until": circuit["until"],
            "reason": circuit["reason"],
        },
        "type_counts": inventory.type_counts,
        "logs": [
            {
                "level": row.level,
                "message": row.message,
                "created_at": row.created_at,
            }
            for row in logs
        ],
    }
