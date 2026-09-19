"""health 路由：存活与就绪探针。

- GET /api/health：存活检查（liveness），进程存活即 200。
- GET /api/ready：就绪检查（readiness），检查数据库 + AList 可达性。
  全部正常 → 200 ready；AList 离线但数据库正常 → 200 degraded；
  数据库不可用 → 503 not_ready。AList 离线标降级，不触发重启或开放匿名访问。
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from .. import __version__
from ..modules.providers.contracts.public import check_provider_health
from ..platform.health import (
    check_database_health,
    health_checks_enabled,
    persist_health_component,
    utcnow_iso,
)

router = APIRouter()


def _utcnow_iso() -> str:
    return utcnow_iso()


async def _check_database(state) -> tuple[str, str | None]:
    """检查 state.db 可连接。返回 (status, error)。"""
    return await check_database_health(state)


async def _check_alist(state) -> tuple[str, str | None]:
    """检查 AList 可达性；未启用时视为 healthy。"""
    return await check_provider_health(state)


async def _persist_component(
    state,
    component: str,
    status: str,
    error: str | None,
) -> None:
    await persist_health_component(
        state,
        component=component,
        status=status,
        error=error,
    )


@router.get("/api/health")
async def health():
    """存活检查：进程存活即 200。"""
    return {"status": "healthy", "version": __version__}


@router.get("/api/ready")
async def ready():
    """就绪检查：数据库 + AList。数据库不可用返回 503，AList 离线标降级。"""
    from ..main import StateSession

    components: dict[str, dict[str, str | None]] = {}
    db_status = "unhealthy"
    db_error: str | None = None
    try:
        async with StateSession() as state:
            db_status, db_error = await _check_database(state)
            components["database"] = {"status": db_status, "error": db_error}
            await _persist_component(state, "database", db_status, db_error)
            if db_status == "healthy":
                enabled = await health_checks_enabled(state)
                if enabled:
                    alist_status, alist_error = await _check_alist(state)
                    components["alist"] = {"status": alist_status, "error": alist_error}
                    await _persist_component(state, "alist", alist_status, alist_error)
                else:
                    components["alist"] = {"status": "healthy", "error": None}
    except Exception as exc:
        db_status = "unhealthy"
        db_error = str(exc)
        components.setdefault("database", {"status": "unhealthy", "error": db_error})

    if db_status != "healthy":
        return JSONResponse({"status": "not_ready", "components": components}, status_code=503)
    alist_info = components.get("alist", {"status": "healthy", "error": None})
    if alist_info["status"] != "healthy":
        return {"status": "degraded", "components": components}
    return {"status": "ready", "components": components}
