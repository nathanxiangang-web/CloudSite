"""admin/collections 路由：合集管理。"""
from fastapi import APIRouter, HTTPException
from sqlalchemy import delete, desc, select

from ...models import Collection, CollectionItem, Resource
from ...schemas import CollectionInput, CollectionItemsInput
from ...services.collections import collection_dict

router = APIRouter()


@router.get("/api/admin/collections")
async def admin_collections():
    from ...main import StateSession, IndexSession

    async with StateSession() as state, IndexSession() as index:
        rows = list((await state.scalars(select(Collection).order_by(Collection.sort_order, desc(Collection.updated_at)))).all())
        return {"items": [await collection_dict(state, index, row) for row in rows]}


@router.get("/api/admin/collections/{collection_id}")
async def admin_collection_detail(collection_id: int):
    from ...main import StateSession, IndexSession

    async with StateSession() as state, IndexSession() as index:
        row = await state.get(Collection, collection_id)
        if not row:
            raise HTTPException(404, "合集不存在")
        items = list((await state.scalars(select(CollectionItem).where(CollectionItem.collection_id == collection_id).order_by(CollectionItem.sort_order, CollectionItem.id))).all())
        resource_ids = [item.resource_id for item in items]
        resources_by_id = {}
        if resource_ids:
            resources_by_id = {resource.id: resource for resource in (await index.scalars(select(Resource).where(Resource.id.in_(resource_ids)))).all()}
        payload = {
            "id": row.id,
            "name": row.name,
            "description": row.description,
            "cover": row.cover,
            "status": row.status,
            "visible_on_home": row.visible_on_home,
            "sort_order": row.sort_order,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "items": [],
        }
        for item in items:
            resource = resources_by_id.get(item.resource_id)
            if resource and resource.status == "active":
                payload["items"].append({"resource_id": item.resource_id, "name": resource.name, "content_type": resource.content_type, "extension": resource.extension, "size": resource.size, "active": True})
            else:
                payload["items"].append({"resource_id": item.resource_id, "name": None, "content_type": "", "extension": "", "size": 0, "active": False})
        return payload


@router.post("/api/admin/collections")
async def create_collection(payload: CollectionInput):
    from ...main import StateSession

    async with StateSession() as session:
        row = Collection(**payload.model_dump())
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return {"id": row.id}


@router.put("/api/admin/collections/{collection_id}")
async def update_collection(collection_id: int, payload: CollectionInput):
    from ...main import StateSession

    async with StateSession() as session:
        row = await session.get(Collection, collection_id)
        if not row:
            raise HTTPException(404, "合集不存在")
        for key, value in payload.model_dump().items():
            setattr(row, key, value)
        await session.commit()
        return {"ok": True}


@router.put("/api/admin/collections/{collection_id}/items")
async def set_collection_items(collection_id: int, payload: CollectionItemsInput):
    from ...main import StateSession, IndexSession

    async with StateSession() as state, IndexSession() as index:
        if not await state.get(Collection, collection_id):
            raise HTTPException(404, "合集不存在")
        resource_ids = list(dict.fromkeys(payload.resource_ids))
        if resource_ids:
            existing = set((await index.scalars(select(Resource.id).where(Resource.id.in_(resource_ids), Resource.status == "active"))).all())
            missing = [resource_id for resource_id in resource_ids if resource_id not in existing]
            if missing:
                raise HTTPException(400, f"资源不存在：{', '.join(missing[:5])}")
        await state.execute(delete(CollectionItem).where(CollectionItem.collection_id == collection_id))
        state.add_all([CollectionItem(collection_id=collection_id, resource_id=resource_id, sort_order=position) for position, resource_id in enumerate(resource_ids)])
        await state.commit()
        return {"ok": True, "item_count": len(resource_ids)}


@router.delete("/api/admin/collections/{collection_id}")
async def delete_collection(collection_id: int):
    from ...main import StateSession

    async with StateSession() as session:
        row = await session.get(Collection, collection_id)
        if not row:
            raise HTTPException(404, "合集不存在")
        await session.delete(row)
        await session.commit()
        return {"ok": True}