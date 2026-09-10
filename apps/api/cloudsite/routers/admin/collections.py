"""admin/collections 路由：合集管理。"""
from fastapi import APIRouter, HTTPException
from sqlalchemy import delete, desc, select

from ...models import CatalogEntry, Collection, CollectionItem, Resource
from ...schemas import CollectionInput, CollectionItemsInput
from ...services.collections import collection_dict
from ..home import invalidate_home_cache

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
        resource_ids = [item.resource_id for item in items if item.item_type == "resource" and item.resource_id]
        entry_ids = [item.catalog_entry_id for item in items if item.item_type == "catalog_entry" and item.catalog_entry_id]
        resources_by_id = {resource.id: resource for resource in (await index.scalars(select(Resource).where(Resource.id.in_(resource_ids)))).all()} if resource_ids else {}
        entries_by_id = {entry.entry_id: entry for entry in (await state.scalars(select(CatalogEntry).where(CatalogEntry.entry_id.in_(entry_ids)))).all()} if entry_ids else {}
        payload = {
            "id": row.id,
            "name": row.name,
            "description": row.description,
            "cover": row.cover,
            "status": row.status,
            "visible_on_home": row.visible_on_home,
            "sort_order": row.sort_order,
            "goal": row.goal,
            "audience": row.audience,
            "prerequisites": row.prerequisites,
            "item_intro": row.item_intro,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "items": [],
        }
        for item in items:
            if item.item_type == "resource" and item.resource_id:
                resource = resources_by_id.get(item.resource_id)
                active = bool(resource and resource.status == "active")
                payload["items"].append({
                    "item_type": "resource",
                    "resource_id": item.resource_id,
                    "name": resource.name if active else None,
                    "content_type": resource.content_type if active else "",
                    "extension": resource.extension if active else "",
                    "size": resource.size if active else 0,
                    "active": active,
                    "note": item.note,
                    "sort_order": item.sort_order,
                })
            elif item.item_type == "catalog_entry" and item.catalog_entry_id:
                entry = entries_by_id.get(item.catalog_entry_id)
                payload["items"].append({
                    "item_type": "catalog_entry",
                    "catalog_entry_id": item.catalog_entry_id,
                    "title": entry.title if entry else None,
                    "content_type": entry.content_type if entry else "",
                    "status": entry.status if entry else None,
                    "active": bool(entry and entry.status == "published"),
                    "note": item.note,
                    "sort_order": item.sort_order,
                })
        return payload


@router.post("/api/admin/collections")
async def create_collection(payload: CollectionInput):
    from ...main import StateSession

    async with StateSession() as session:
        row = Collection(**payload.model_dump())
        session.add(row)
        await session.commit()
        await session.refresh(row)
        invalidate_home_cache()
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
        invalidate_home_cache()
        return {"ok": True}


@router.put("/api/admin/collections/{collection_id}/items")
async def set_collection_items(collection_id: int, payload: CollectionItemsInput):
    from ...main import StateSession, IndexSession

    async with StateSession() as state, IndexSession() as index:
        if not await state.get(Collection, collection_id):
            raise HTTPException(404, "合集不存在")
        if payload.items is not None:
            normalized: list[CollectionItem] = []
            seen: set[tuple[str, str]] = set()
            for position, raw in enumerate(payload.items):
                if raw.item_type == "resource":
                    if not raw.resource_id:
                        raise HTTPException(400, "resource 条目缺少 resource_id")
                    key = ("resource", raw.resource_id)
                    if key in seen:
                        continue
                    seen.add(key)
                    normalized.append(CollectionItem(collection_id=collection_id, item_type="resource", resource_id=raw.resource_id, catalog_entry_id=None, note=raw.note, sort_order=position))
                else:
                    if not raw.catalog_entry_id:
                        raise HTTPException(400, "catalog_entry 条目缺少 catalog_entry_id")
                    key = ("catalog_entry", raw.catalog_entry_id)
                    if key in seen:
                        continue
                    seen.add(key)
                    normalized.append(CollectionItem(collection_id=collection_id, item_type="catalog_entry", resource_id=None, catalog_entry_id=raw.catalog_entry_id, note=raw.note, sort_order=position))
            resource_ids = [item.resource_id for item in normalized if item.item_type == "resource"]
            entry_ids = [item.catalog_entry_id for item in normalized if item.item_type == "catalog_entry"]
            if resource_ids:
                existing_resources = set((await index.scalars(select(Resource.id).where(Resource.id.in_(resource_ids), Resource.status == "active"))).all())
                missing_resources = [rid for rid in resource_ids if rid not in existing_resources]
                if missing_resources:
                    raise HTTPException(400, f"资源不存在：{', '.join(missing_resources[:5])}")
            if entry_ids:
                existing_entries = set((await state.scalars(select(CatalogEntry.entry_id).where(CatalogEntry.entry_id.in_(entry_ids)))).all())
                missing_entries = [eid for eid in entry_ids if eid not in existing_entries]
                if missing_entries:
                    raise HTTPException(400, f"Catalog 条目不存在：{', '.join(missing_entries[:5])}")
            await state.execute(delete(CollectionItem).where(CollectionItem.collection_id == collection_id))
            state.add_all(normalized)
            await state.commit()
            invalidate_home_cache()
            return {"ok": True, "item_count": len(normalized)}
        resource_ids = list(dict.fromkeys(payload.resource_ids))
        if resource_ids:
            existing = set((await index.scalars(select(Resource.id).where(Resource.id.in_(resource_ids), Resource.status == "active"))).all())
            missing = [resource_id for resource_id in resource_ids if resource_id not in existing]
            if missing:
                raise HTTPException(400, f"资源不存在：{', '.join(missing[:5])}")
        await state.execute(delete(CollectionItem).where(CollectionItem.collection_id == collection_id))
        state.add_all([CollectionItem(collection_id=collection_id, item_type="resource", resource_id=resource_id, sort_order=position) for position, resource_id in enumerate(resource_ids)])
        await state.commit()
        invalidate_home_cache()
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
        invalidate_home_cache()
        return {"ok": True}
