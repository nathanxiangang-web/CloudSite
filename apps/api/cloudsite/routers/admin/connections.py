"""admin/connections 路由：多连接管理 + Provider 兼容记录。"""

from fastapi import APIRouter, HTTPException

from ...connection_schemas import (
    CompatRecordCreate,
    ConnectionCreate,
    ConnectionToggle,
    ConnectionUpdate,
)
from ...services.connections import (
    ConnectionResult,
    all_enabled_connections,
    create_connection,
    delete_connection,
    get_connection,
    get_connection_roots,
    list_compat_records,
    list_connections,
    record_compat,
    toggle_connection,
    update_connection,
)

router = APIRouter()


def _conn_to_dict(conn) -> dict:
    return {
        "id": conn.id,
        "name": conn.name,
        "base_url": conn.base_url,
        "username": conn.username,
        "remember_credentials": conn.remember_credentials,
        "enabled": conn.enabled,
        "provider_type": conn.provider_type,
        "last_test_status": conn.last_test_status,
        "last_test_message": conn.last_test_message,
        "last_test_at": conn.last_test_at,
        "has_password": bool(conn.password_ciphertext),
        "created_at": conn.created_at,
        "updated_at": conn.updated_at,
    }


@router.get("/api/admin/connections")
async def get_connections():
    from ...main import StateSession

    async with StateSession() as session:
        conns = await list_connections(session)
        return {"items": [_conn_to_dict(c) for c in conns]}


@router.post("/api/admin/connections")
async def post_connection(payload: ConnectionCreate):
    from ...main import StateSession

    async with StateSession() as session:
        result = await create_connection(
            session,
            name=payload.name,
            base_url=payload.base_url,
            username=payload.username,
            password=payload.password,
            remember_credentials=payload.remember_credentials,
            provider_type=payload.provider_type,
        )
        if not result.ok:
            raise HTTPException(400, result.message)
        return {"ok": True, "message": result.message, "connection_id": result.connection_id}


@router.get("/api/admin/connections/compat-records")
async def get_compat_records():
    from ...main import StateSession

    async with StateSession() as session:
        records = await list_compat_records(session)
        return {
            "items": [
                {
                    "id": r.id,
                    "provider_type": r.provider_type,
                    "adapter_version": r.adapter_version,
                    "platform": r.platform,
                    "platform_version": r.platform_version,
                    "test_result": r.test_result,
                    "tested_capabilities_json": r.tested_capabilities_json,
                    "notes": r.notes,
                    "created_at": r.created_at,
                }
                for r in records
            ]
        }


@router.post("/api/admin/connections/compat-records")
async def post_compat_record(payload: CompatRecordCreate):
    from ...main import StateSession

    async with StateSession() as session:
        record = await record_compat(
            session,
            provider_type=payload.provider_type,
            adapter_version=payload.adapter_version,
            platform=payload.platform,
            platform_version=payload.platform_version,
            test_result=payload.test_result,
            tested_capabilities_json=payload.tested_capabilities_json,
            notes=payload.notes,
        )
        return {"ok": True, "record_id": record.id}


@router.get("/api/admin/connections/{connection_id}")
async def get_one_connection(connection_id: int):
    from ...main import StateSession

    async with StateSession() as session:
        conn = await get_connection(session, connection_id)
        if not conn:
            raise HTTPException(404, "连接不存在")
        roots = await get_connection_roots(session, connection_id)
        return {
            **_conn_to_dict(conn),
            "roots": [
                {
                    "id": r.id,
                    "content_type": r.content_type,
                    "display_name": r.display_name,
                    "alist_path": r.alist_path,
                    "enabled": r.enabled,
                }
                for r in roots
            ],
        }


@router.put("/api/admin/connections/{connection_id}")
async def put_connection(connection_id: int, payload: ConnectionUpdate):
    from ...main import StateSession

    async with StateSession() as session:
        result = await update_connection(
            session,
            connection_id,
            name=payload.name,
            base_url=payload.base_url,
            username=payload.username,
            password=payload.password,
            remember_credentials=payload.remember_credentials,
            provider_type=payload.provider_type,
        )
        if not result.ok:
            raise HTTPException(404, result.message)
        return {"ok": True, "message": result.message}


@router.patch("/api/admin/connections/{connection_id}/enabled")
async def patch_connection_enabled(connection_id: int, payload: ConnectionToggle):
    from ...main import StateSession

    async with StateSession() as session:
        result = await toggle_connection(session, connection_id, payload.enabled)
        if not result.ok:
            raise HTTPException(404, result.message)
        return {"ok": True, "message": result.message}


@router.delete("/api/admin/connections/{connection_id}")
async def del_connection(connection_id: int):
    from ...main import StateSession

    async with StateSession() as session:
        result = await delete_connection(session, connection_id)
        if not result.ok:
            status = 400 if "不可删除" in result.message else 404
            raise HTTPException(status, result.message)
        return {"ok": True, "message": result.message}
