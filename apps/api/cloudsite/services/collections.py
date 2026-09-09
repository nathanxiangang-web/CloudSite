"""collections 服务：合集序列化辅助函数。"""
from sqlalchemy import select

from ..models import Collection, CollectionItem, Resource
from ..shares.service import enabled_root_ids
from .resources import resource_dict


async def collection_dict(state, index, row: Collection, include_items: bool = False) -> dict:
    items = list((await state.scalars(select(CollectionItem).where(CollectionItem.collection_id == row.id).order_by(CollectionItem.sort_order, CollectionItem.id))).all())
    resource_ids = [item.resource_id for item in items]
    resources_by_id = {}
    if resource_ids:
        roots = await enabled_root_ids(state)
        if roots:
            resources_by_id = {
                resource.id: resource
                for resource in (
                    await index.scalars(
                        select(Resource).where(
                            Resource.id.in_(resource_ids),
                            Resource.status == "active",
                            Resource.root_mapping_id.in_(roots),
                        )
                    )
                ).all()
            }
    payload = {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "cover": row.cover,
        "status": row.status,
        "visible_on_home": row.visible_on_home,
        "sort_order": row.sort_order,
        "item_count": len(resources_by_id),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
    if include_items:
        payload["items"] = [resource_dict(resources_by_id[item.resource_id]) for item in items if item.resource_id in resources_by_id]
    return payload
