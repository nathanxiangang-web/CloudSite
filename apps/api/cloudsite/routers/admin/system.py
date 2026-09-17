"""admin/system 路由：系统设置。"""
from fastapi import APIRouter
from sqlalchemy import func, select

from ... import __version__
from ...models import Folder, OperationLog, Resource, SystemSetting
from ...modules.providers.application.provider_service import provider_info
from ...schemas import SystemInput

router = APIRouter()


@router.get("/api/admin/system")
async def get_system():
    from ...main import StateSession, IndexSession, get_system_values

    async with StateSession() as state, IndexSession() as index:
        values = await get_system_values(state)
        engine_version_row = await state.get(SystemSetting, "sync_engine_version")
        initial_index_row = await state.get(SystemSetting, "initial_index_completed_at")
        values.update({
            "version": __version__,
            "database": "SQLite 3",
            "timezone": "Asia/Shanghai",
            "resources": int(await index.scalar(select(func.count()).select_from(Resource).where(Resource.status == "active")) or 0),
            "folders": int(await index.scalar(select(func.count()).select_from(Folder).where(Folder.status == "active")) or 0),
            "operation_logs": int(await state.scalar(select(func.count()).select_from(OperationLog)) or 0),
            "sync_engine_version": engine_version_row.value if engine_version_row else "1.0",
            "initial_index_completed_at": initial_index_row.value if initial_index_row else None,
        })
        values["provider"] = await provider_info(state)
    return values


@router.put("/api/admin/system")
async def save_system(payload: SystemInput):
    from ...main import StateSession

    async with StateSession() as session:
        for key, value in payload.model_dump().items():
            row = await session.get(SystemSetting, key) or SystemSetting(key=key)
            row.value = str(value).lower() if isinstance(value, bool) else str(value)
            session.add(row)
        await session.commit()
        return {"ok": True}