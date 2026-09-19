"""Delivery-owned download diagnostics workflow."""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from cloudsite.modules.providers.contracts.public import ProviderRuntimePort
from cloudsite.modules.resources.contracts.public import DiagnosticResourceView

from ..domain.download import DownloadError, resolve_download_entry
from ..infrastructure.models import DownloadDiagnostic


def download_diagnostic_dict(row: DownloadDiagnostic) -> dict[str, Any]:
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


async def _persist(
    state: AsyncSession,
    diagnostic: DownloadDiagnostic,
) -> None:
    state.add(diagnostic)
    await state.commit()
    await state.refresh(diagnostic)


async def diagnose_download(
    state: AsyncSession,
    *,
    resource_id: str,
    resource: DiagnosticResourceView | None,
    provider_runtime: ProviderRuntimePort,
) -> dict[str, Any]:
    started = time.perf_counter()
    steps: list[dict[str, Any]] = []

    if resource is None:
        steps.append(
            {
                "name": "resource_lookup",
                "status": "failed",
                "duration_ms": 0,
            }
        )
        diagnostic = DownloadDiagnostic(
            resource_id=resource_id,
            status="failed",
            failed_step="resource_lookup",
            error_code="DL-001",
            message="资源不存在或已失效",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        await _persist(state, diagnostic)
        return {
            **download_diagnostic_dict(diagnostic),
            "resource_name": "",
            "has_sign": False,
            "base_path": "",
            "steps": steps,
        }

    steps.append(
        {
            "name": "resource_lookup",
            "status": "success",
            "duration_ms": 0,
        }
    )
    if resource.status != "active":
        code = "DL-001" if resource.status == "missing" else "DL-007"
        steps.append(
            {
                "name": "resource_status",
                "status": "failed",
                "duration_ms": 0,
            }
        )
        diagnostic = DownloadDiagnostic(
            resource_id=resource.id,
            status="failed",
            failed_step="resource_status",
            error_code=code,
            message="资源不存在或当前禁止下载",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        await _persist(state, diagnostic)
        return {
            **download_diagnostic_dict(diagnostic),
            "resource_name": resource.name,
            "has_sign": False,
            "base_path": "",
            "steps": steps,
        }

    steps.append(
        {
            "name": "resource_status",
            "status": "success",
            "duration_ms": 0,
        }
    )
    try:
        resolution = await resolve_download_entry(
            resource,
            provider_runtime,
        )
        steps.extend(resolution.steps)
        diagnostic = DownloadDiagnostic(
            resource_id=resource.id,
            status="success",
            message="下载跳转已就绪",
            duration_ms=int((time.perf_counter() - started) * 1000),
            target_host=resolution.target_host,
        )
        await _persist(state, diagnostic)
        return {
            **download_diagnostic_dict(diagnostic),
            "resource_name": resource.name,
            "has_sign": resolution.has_sign,
            "base_path": resolution.base_path,
            "steps": steps,
        }
    except DownloadError as exc:
        steps.append(
            {
                "name": exc.failed_step,
                "status": "failed",
                "duration_ms": int(
                    (time.perf_counter() - started) * 1000
                ),
            }
        )
        diagnostic = DownloadDiagnostic(
            resource_id=resource.id,
            status="failed",
            failed_step=exc.failed_step,
            error_code=exc.code,
            message=exc.message,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        await _persist(state, diagnostic)
        return {
            **download_diagnostic_dict(diagnostic),
            "resource_name": resource.name,
            "has_sign": False,
            "base_path": "",
            "steps": steps,
        }


async def list_download_diagnostics(
    state: AsyncSession,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    rows = list(
        (
            await state.scalars(
                select(DownloadDiagnostic)
                .order_by(desc(DownloadDiagnostic.id))
                .limit(limit)
            )
        ).all()
    )
    return [download_diagnostic_dict(row) for row in rows]


__all__ = [
    "diagnose_download",
    "download_diagnostic_dict",
    "list_download_diagnostics",
]
