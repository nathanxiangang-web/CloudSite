"""admin/collections 路由：合集管理。"""

from fastapi import APIRouter, HTTPException

from ...modules.collections.contracts.public import (
    CollectionNotFound,
    CollectionValidationError,
    create_collection,
    delete_collection,
    get_admin_collection,
    list_admin_collections,
    replace_collection_items,
    update_collection,
)
from ...schemas import CollectionInput, CollectionItemsInput
from ..home import invalidate_home_cache

router = APIRouter()


@router.get("/api/admin/collections")
async def admin_collections():
    from ...main import IndexSession, StateSession

    async with StateSession() as state, IndexSession() as index:
        return {"items": await list_admin_collections(state, index)}


@router.get("/api/admin/collections/{collection_id}")
async def admin_collection_detail(collection_id: int):
    from ...main import IndexSession, StateSession

    async with StateSession() as state, IndexSession() as index:
        try:
            return await get_admin_collection(state, index, collection_id)
        except CollectionNotFound as exc:
            raise HTTPException(404, "合集不存在") from exc


@router.post("/api/admin/collections")
async def create_collection_route(payload: CollectionInput):
    from ...main import StateSession

    async with StateSession() as state:
        collection_id = await create_collection(
            state,
            values=payload.model_dump(),
        )
    invalidate_home_cache()
    return {"id": collection_id}


@router.put("/api/admin/collections/{collection_id}")
async def update_collection_route(
    collection_id: int,
    payload: CollectionInput,
):
    from ...main import StateSession

    async with StateSession() as state:
        try:
            await update_collection(
                state,
                collection_id,
                values=payload.model_dump(),
            )
        except CollectionNotFound as exc:
            raise HTTPException(404, "合集不存在") from exc
    invalidate_home_cache()
    return {"ok": True}


@router.put("/api/admin/collections/{collection_id}/items")
async def set_collection_items(
    collection_id: int,
    payload: CollectionItemsInput,
):
    from ...main import IndexSession, StateSession

    items = (
        [item.model_dump() for item in payload.items]
        if payload.items is not None
        else None
    )
    async with StateSession() as state, IndexSession() as index:
        try:
            item_count = await replace_collection_items(
                state,
                index,
                collection_id,
                items=items,
                resource_ids=payload.resource_ids,
            )
        except CollectionNotFound as exc:
            raise HTTPException(404, "合集不存在") from exc
        except CollectionValidationError as exc:
            raise HTTPException(400, str(exc)) from exc
    invalidate_home_cache()
    return {"ok": True, "item_count": item_count}


@router.delete("/api/admin/collections/{collection_id}")
async def delete_collection_route(collection_id: int):
    from ...main import StateSession

    async with StateSession() as state:
        try:
            await delete_collection(state, collection_id)
        except CollectionNotFound as exc:
            raise HTTPException(404, "合集不存在") from exc
    invalidate_home_cache()
    return {"ok": True}
