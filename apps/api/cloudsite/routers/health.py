"""health 路由：存活与就绪探针。

- GET /api/health：存活检查（liveness），进程存活即 200。
- GET /api/ready：就绪检查（readiness），检查数据库 + AList 可达性。
  全部正常 → 200 ready；AList 离线但数据库正常 → 200 degraded；
  数据库不可用 → 503 not_ready。AList 离线标降级，不触发重启或开放匿名访问。
"""
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import select

from .. import __version__
from ..models import AListConnection, HealthCheckState, SystemSetting

router = APIRouter()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _check_database(state) -> tuple[str, str | None]:
    """检查 state.db 可连接。返回 (status, error)。"""
    try:
        await state.execute(select(SystemSetting.key).limit(1))
        return "healthy", None
    except Exception as exc:
        return "unhealthy", str(exc)


async def _check_alist(state) -> tuple[str, str | None]:
    """检查 AList 可达。未配置或未启用视为 healthy。

    配置启用但连接失败标 degraded（不阻断就绪，仅提示）。返回 (status, error)。
    """
    try:
        connection = await state.get(AListConnection, 1)
    except Exception as exc:
        return "degraded", str(exc)
    if not connection or not connection.enabled:
        return "healthy", None
    try:
        from ..alist import AListClient
        from ..crypto import decrypt_secret

        password = decrypt_secret(connection.password_ciphertext)
        async with AListClient(connection.base_url, connection.username, password) as client:
            await client.test()
        return "healthy", None
    except Exception as exc:
        return "degraded", str(exc)


async def _persist_component(state, component: str, status: str, error: str | None) -> None:
    """幂等更新 health_check_state 对应组件行。"""
    try:
        existing = await state.scalar(
            select(HealthCheckState).where(HealthCheckState.component == component)
        )
        now = _utcnow_iso()
        if existing:
            existing.status = status
            existing.last_check_at = now
            existing.last_error = error
        else:
            state.add(HealthCheckState(component=component, status=status, last_check_at=now, last_error=error))
        await state.commit()
    except Exception:
        await state.rollback()


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
                enabled = True
                try:
                    setting = await state.get(SystemSetting, "health_check_enabled")
                    if setting is not None:
                        enabled = (setting.value or "").lower() not in ("false", "0", "no", "off")
                except Exception:
                    pass
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
