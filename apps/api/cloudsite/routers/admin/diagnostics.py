"""admin/diagnostics 路由：下载诊断。"""
import time

from fastapi import APIRouter, Query
from sqlalchemy import desc, select

from ...download import DownloadError, resolve_download_entry
from ...models import AListConnection, DownloadDiagnostic, Resource
from ...schemas import DownloadDiagnosticInput

router = APIRouter()


def download_diagnostic_dict(row: DownloadDiagnostic) -> dict:
    return {
        "id": row.id,
        "resource_id": row.resource_id,
        "status": row.status,
        "failed_step": row.failed_step,
        "error_code": row.error_code,
        "message": row.message,
        "duration_ms": row.duration_ms,
        "target_host": row.target_host,
        "created_at": row.created_at,
    }


@router.post("/api/admin/downloads/diagnose")
async def diagnose_download(payload: DownloadDiagnosticInput):
    from ...main import StateSession, IndexSession

    started = time.perf_counter()
    steps: list[dict] = []
    async with IndexSession() as index, StateSession() as state:
        resource = await index.get(Resource, payload.resource_id)
        if not resource:
            steps.append({"name": "resource_lookup", "status": "failed", "duration_ms": 0})
            diagnostic = DownloadDiagnostic(resource_id=payload.resource_id, status="failed", failed_step="resource_lookup", error_code="DL-001", message="资源不存在或已失效", duration_ms=int((time.perf_counter() - started) * 1000))
            state.add(diagnostic)
            await state.commit()
            return {**download_diagnostic_dict(diagnostic), "resource_name": "", "has_sign": False, "base_path": "", "steps": steps}
        steps.append({"name": "resource_lookup", "status": "success", "duration_ms": 0})
        if resource.status != "active":
            code = "DL-001" if resource.status == "missing" else "DL-007"
            steps.append({"name": "resource_status", "status": "failed", "duration_ms": 0})
            diagnostic = DownloadDiagnostic(resource_id=resource.id, status="failed", failed_step="resource_status", error_code=code, message="资源不存在或当前禁止下载", duration_ms=int((time.perf_counter() - started) * 1000))
            state.add(diagnostic)
            await state.commit()
            return {**download_diagnostic_dict(diagnostic), "resource_name": resource.name, "has_sign": False, "base_path": "", "steps": steps}
        steps.append({"name": "resource_status", "status": "success", "duration_ms": 0})
        connection = await state.get(AListConnection, 1)
        try:
            resolution = await resolve_download_entry(resource, connection)
            steps.extend(resolution.steps)
            diagnostic = DownloadDiagnostic(resource_id=resource.id, status="success", message="下载跳转已就绪", duration_ms=int((time.perf_counter() - started) * 1000), target_host=resolution.target_host)
            state.add(diagnostic)
            await state.commit()
            return {**download_diagnostic_dict(diagnostic), "resource_name": resource.name, "has_sign": resolution.has_sign, "base_path": resolution.base_path, "steps": steps}
        except DownloadError as exc:
            steps.append({"name": exc.failed_step, "status": "failed", "duration_ms": int((time.perf_counter() - started) * 1000)})
            diagnostic = DownloadDiagnostic(resource_id=resource.id, status="failed", failed_step=exc.failed_step, error_code=exc.code, message=exc.message, duration_ms=int((time.perf_counter() - started) * 1000))
            state.add(diagnostic)
            await state.commit()
            return {**download_diagnostic_dict(diagnostic), "resource_name": resource.name, "has_sign": False, "base_path": "", "steps": steps}


@router.get("/api/admin/downloads/diagnostics")
async def download_diagnostic_history(limit: int = Query(20, ge=1, le=100)):
    from ...main import StateSession

    async with StateSession() as session:
        rows = list((await session.scalars(select(DownloadDiagnostic).order_by(desc(DownloadDiagnostic.id)).limit(limit))).all())
        return {"items": [download_diagnostic_dict(row) for row in rows]}