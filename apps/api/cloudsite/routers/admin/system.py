"""admin/system 路由：系统设置。"""

from fastapi import APIRouter

from ... import __version__
from ...modules.providers.contracts.public import provider_info
from ...modules.resources.contracts.public import resource_queries
from ...platform.observability import count_operation_logs
from ...platform.settings import (
    read_admin_system_settings,
    save_admin_system_settings,
)
from ...schemas import SystemInput

router = APIRouter()


@router.get("/api/admin/system")
async def get_system():
    from ...main import IndexSession, StateSession

    async with StateSession() as state, IndexSession() as index:
        values = await read_admin_system_settings(state)
        counts = await resource_queries(index).admin_index_counts()
        values.update(
            {
                "version": __version__,
                "database": "SQLite 3",
                "timezone": "Asia/Shanghai",
                "resources": counts.resources,
                "folders": counts.folders,
                "operation_logs": await count_operation_logs(state),
            }
        )
        values["provider"] = await provider_info(state)
        return values


@router.put("/api/admin/system")
async def save_system(payload: SystemInput):
    from ...main import StateSession

    async with StateSession() as state:
        await save_admin_system_settings(
            state,
            values=payload.model_dump(),
        )
        return {"ok": True}
