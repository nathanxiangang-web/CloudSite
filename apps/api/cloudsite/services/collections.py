"""collections 服务：合集序列化辅助函数。"""
from sqlalchemy import select

from ..models import CatalogEntry, Collection, CollectionItem, Resource
from ..shares.service import enabled_root_ids
from .resources import resource_dict


async def collection_dict(state, index, row: Collection, include_items: bool = False) -> dict:
    items = list((await state.scalars(select(CollectionItem).where(CollectionItem.collection_id == row.id).order_by(CollectionItem.sort_order, CollectionItem.id))).all())
    resource_items = [item for item in items if item.item_type == "resource" and item.resource_id]
    catalog_items = [item for item in items if item.item_type == "catalog_entry" and item.catalog_entry_id]

    resources_by_id = {}
    if resource_items:
        roots = await enabled_root_ids(state)
        if roots:
            resources_by_id = {
                resource.id: resource
                for resource in (
                    await index.scalars(
                        select(Resource).where(
                            Resource.id.in_([item.resource_id for item in resource_items]),
                            Resource.status == "active",
                            Resource.root_mapping_id.in_(roots),
                        )
                    )
                ).all()
            }

    entries_by_id = {}
    if catalog_items:
        entries_by_id = {
            entry.entry_id: entry
            for entry in (
                await state.scalars(
                    select(CatalogEntry).where(
                        CatalogEntry.entry_id.in_([item.catalog_entry_id for item in catalog_items]),
                        CatalogEntry.status == "published",
                    )
                )
            ).all()
        }

    visible_resource_count = sum(1 for item in resource_items if item.resource_id in resources_by_id)
    visible_catalog_count = sum(1 for item in catalog_items if item.catalog_entry_id in entries_by_id)
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
        "item_count": visible_resource_count + visible_catalog_count,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
    if include_items:
        serialized = []
        for item in items:
            if item.item_type == "resource" and item.resource_id and item.resource_id in resources_by_id:
                entry = resource_dict(resources_by_id[item.resource_id])
                entry["item_type"] = "resource"
                entry["note"] = item.note
                serialized.append(entry)
            elif item.item_type == "catalog_entry" and item.catalog_entry_id and item.catalog_entry_id in entries_by_id:
                catalog_entry = entries_by_id[item.catalog_entry_id]
                serialized.append({
                    "item_type": "catalog_entry",
                    "catalog_entry_id": catalog_entry.entry_id,
                    "id": catalog_entry.entry_id,
                    "name": catalog_entry.title,
                    "title": catalog_entry.title,
                    "summary": catalog_entry.summary,
                    "content_type": catalog_entry.content_type,
                    "cover_resource_id": catalog_entry.cover_resource_id,
                    "note": item.note,
                    "sort_order": item.sort_order,
                })
        payload["items"] = serialized
    return payload
