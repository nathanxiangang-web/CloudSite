"""collections 路由：公共合集。"""
from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from ..models import Collection
from ..services.collections import collection_dict

router = APIRouter()


@router.get("/api/collections")
async def public_collections():
    from ..main import StateSession, IndexSession

    async with StateSession() as state, IndexSession() as index:
        rows = list((await state.scalars(select(Collection).where(Collection.status == "active").order_by(Collection.sort_order, Collection.name))).all())
        return {"items": [await collection_dict(state, index, row) for row in rows]}


@router.get("/api/collections/{collection_id}")
async def public_collection_detail(collection_id: int):
    from ..main import StateSession, IndexSession

    async with StateSession() as state, IndexSession() as index:
        row = await state.get(Collection, collection_id)
        if not row or row.status != "active":
            raise HTTPException(404, "合集不存在")
        return await collection_dict(state, index, row, include_items=True)
