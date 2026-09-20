"""collections 路由：公共合集。"""

from fastapi import APIRouter, HTTPException

from ..modules.collections.contracts.public import (
    CollectionNotFound,
    get_public_collection,
    list_public_collections,
)

router = APIRouter()


@router.get("/api/collections")
async def public_collections():
    from ..main import IndexSession, StateSession

    async with StateSession() as state, IndexSession() as index:
        return {"items": await list_public_collections(state, index)}


@router.get("/api/collections/{collection_id}")
async def public_collection_detail(collection_id: int):
    from ..main import IndexSession, StateSession

    async with StateSession() as state, IndexSession() as index:
        try:
            return await get_public_collection(state, index, collection_id)
        except CollectionNotFound as exc:
            raise HTTPException(404, "合集不存在") from exc
