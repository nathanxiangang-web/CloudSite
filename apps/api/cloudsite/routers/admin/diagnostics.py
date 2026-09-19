"""admin/diagnostics routes: delivery download diagnostics."""

from fastapi import APIRouter, Query

from ...modules.delivery.contracts.public import (
    diagnose_download as run_download_diagnostic,
    download_diagnostic_dict as _delivery_diagnostic_dict,
    list_download_diagnostics,
)
from ...modules.providers.contracts.public import provider_runtime
from ...modules.resources.contracts.public import resource_queries
from ...schemas import DownloadDiagnosticInput

router = APIRouter()


def download_diagnostic_dict(row) -> dict:
    """Compatibility serializer re-exported through cloudsite.main."""

    return _delivery_diagnostic_dict(row)


@router.post("/api/admin/downloads/diagnose")
async def diagnose_download(payload: DownloadDiagnosticInput):
    from ...main import IndexSession, StateSession

    async with IndexSession() as index, StateSession() as state:
        resource = await resource_queries(index).diagnostic_resource(
            resource_id=payload.resource_id,
        )
        return await run_download_diagnostic(
            state,
            resource_id=payload.resource_id,
            resource=resource,
            provider_runtime=provider_runtime(state),
        )


@router.get("/api/admin/downloads/diagnostics")
async def download_diagnostic_history(
    limit: int = Query(20, ge=1, le=100),
):
    from ...main import StateSession

    async with StateSession() as state:
        rows = await list_download_diagnostics(
            state,
            limit=limit,
        )
    return {"items": rows}
