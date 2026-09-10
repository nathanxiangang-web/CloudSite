"""B2 admin/publication_scope 路由：管理 CatalogEntry 公开发布范围。

管理员可显式公开/撤回条目。撤回时清除首页缓存与站点地图缓存条目。
公开页面生成独立 DTO（不含管理敏感信息）。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...auth import validate_request_origin
from ...models import CatalogEntry, OperationLog
from ...services.publication_scope import (
    invalidate_sitemap_cache,
    public_entry_dto,
    set_publicly_visible,
)

router = APIRouter()


class PublicationScopeInput(BaseModel):
    publicly_visible: bool


@router.get("/api/admin/publication-scope")
async def list_publication_scope():
    from ...main import StateSession

    from sqlalchemy import select
    async with StateSession() as state:
        rows = list((await state.scalars(
            select(CatalogEntry).order_by(CatalogEntry.sort_order, CatalogEntry.title)
        )).all())
        return {
            "items": [
                {
                    "entry_id": r.entry_id,
                    "title": r.title,
                    "content_type": r.content_type,
                    "status": r.status,
                    "publicly_visible": bool(r.publicly_visible),
                    "published_at": r.published_at.isoformat() if r.published_at else None,
                }
                for r in rows
            ]
        }


@router.put("/api/admin/catalog/entries/{entry_id}/publication-scope")
async def update_publication_scope(entry_id: str, payload: PublicationScopeInput, request: Request):
    from ...main import StateSession

    validate_request_origin(request)
    async with StateSession() as state:
        entry = await set_publicly_visible(state, entry_id, payload.publicly_visible)
        if entry is None:
            raise HTTPException(404, {"code": "CATALOG_ENTRY_NOT_FOUND", "message": "Catalog entry not found"})
        state.add(entry)
        state.add(OperationLog(
            level="INFO",
            module="publication_scope",
            action="publication_scope_updated",
            message=f"条目 {entry_id} 公开范围设为 {'公开' if payload.publicly_visible else '登录可见'}",
        ))
        await state.commit()
        if not payload.publicly_visible:
            invalidate_sitemap_cache()
            from ..home import invalidate_home_cache
            invalidate_home_cache()
    return {"ok": True, "entry_id": entry_id, "publicly_visible": payload.publicly_visible}


@router.get("/api/public/catalog/{entry_id}")
async def public_catalog_entry_dto(entry_id: str):
    """公开页面独立 DTO：仅 publicly_visible=True 且已发布的条目可访问。"""
    from ...main import StateSession

    async with StateSession() as state:
        entry = await state.get(CatalogEntry, entry_id)
        if entry is None or not entry.publicly_visible or entry.status != "published":
            raise HTTPException(404, {"code": "CATALOG_ENTRY_NOT_PUBLIC", "message": "条目未公开"})
        return public_entry_dto(entry)
