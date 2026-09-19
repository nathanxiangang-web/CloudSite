"""admin/overview routes: operational dashboard."""

from fastapi import APIRouter

from ...modules.delivery.contracts.public import count_failed_downloads
from ...modules.indexing.contracts.public import read_v2_sync_progress
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
        progress = await read_v2_sync_progress(state)
        logs = await recent_operation_logs(state, limit=6)

        latest_sync = None
        if progress:
            latest_sync = {
                "id": 0,
                "status": str(progress.get("status", "idle")),
                "finished_at": None,
                "added": 0,
                "updated": 0,
                "removed": 0,
                "folders_scanned": int(
                    progress.get("categories_done", 0) or 0
                ),
                "resources_scanned": int(
                    progress.get("entries_scanned", 0) or 0
                ),
                "current_path": str(
                    progress.get("current_path", "") or ""
                ),
                "roots_total": int(
                    progress.get("categories_total", 0) or 0
                ),
                "roots_completed": int(
                    progress.get("categories_done", 0) or 0
                ),
                "roots_failed": 0,
                "duration_ms": int(
                    progress.get("elapsed_seconds", 0) or 0
                )
                * 1000,
            }

        return {
            "resources": counts.resources,
            "folders": counts.folders,
            "download_failures": failures,
            "alist_connected": alist_connected,
            "latest_sync": latest_sync,
            "type_counts": type_counts,
            "logs": logs,
        }
