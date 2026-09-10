"""admin/content_roots 路由：根目录映射管理。"""
from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from ...alist import AListClient
from ...crypto import decrypt_secret
from ...indexer import normalize_path
from ...models import AListConnection, ContentRootMapping
from ...schemas import RootMappingInput
from ..home import invalidate_home_cache
from .alist import alist_http_exception

router = APIRouter()


@router.get("/api/admin/root-mappings")
async def get_root_mappings():
    from ...main import StateSession

    async with StateSession() as session:
        rows = list((await session.scalars(select(ContentRootMapping).order_by(ContentRootMapping.sort_order))).all())
        return {"items": [{"id": row.id, "content_type": row.content_type, "display_name": row.display_name, "alist_path": row.alist_path, "enabled": row.enabled, "sort_order": row.sort_order} for row in rows]}


async def validate_root_mapping_path(path: str) -> str:
    from ...main import StateSession

    normalized = normalize_path(path)
    async with StateSession() as session:
        connection = await session.get(AListConnection, 1)
    if not connection or not connection.enabled or not connection.password_ciphertext:
        raise HTTPException(409, "请先保存可用的 AList 连接和凭据")
    try:
        client = AListClient(connection.base_url, connection.username, decrypt_secret(connection.password_ciphertext))
        info = await client.get_path(normalized)
    except Exception as exc:
        raise alist_http_exception(exc) from exc
    if info.get("is_dir") is False:
        raise HTTPException(400, "根目录映射必须指向 AList 文件夹")
    return normalized


@router.post("/api/admin/root-mappings")
async def add_root_mapping(payload: RootMappingInput):
    from ...main import StateSession

    normalized_path = await validate_root_mapping_path(payload.alist_path)
    async with StateSession() as session:
        row = ContentRootMapping(**{**payload.model_dump(), "alist_path": normalized_path})
        session.add(row)
        try:
            await session.commit()
        except Exception as exc:
            await session.rollback()
            raise HTTPException(409, "该 AList 根目录已存在") from exc
        await session.refresh(row)
        invalidate_home_cache()
        return {"id": row.id}


@router.put("/api/admin/root-mappings/{mapping_id}")
async def update_root_mapping(mapping_id: int, payload: RootMappingInput):
    from ...main import StateSession

    normalized_path = await validate_root_mapping_path(payload.alist_path)
    async with StateSession() as session:
        row = await session.get(ContentRootMapping, mapping_id)
        if not row:
            raise HTTPException(404, "映射不存在")
        for key, value in {**payload.model_dump(), "alist_path": normalized_path}.items():
            setattr(row, key, value)
        try:
            await session.commit()
        except Exception as exc:
            await session.rollback()
            raise HTTPException(409, "该 AList 根目录已被其他映射使用") from exc
        invalidate_home_cache()
        return {"ok": True}


@router.delete("/api/admin/root-mappings/{mapping_id}")
async def delete_root_mapping(mapping_id: int):
    from ...main import StateSession

    async with StateSession() as session:
        row = await session.get(ContentRootMapping, mapping_id)
        if not row:
            raise HTTPException(404, "映射不存在")
        await session.delete(row)
        await session.commit()
        invalidate_home_cache()
        return {"ok": True}