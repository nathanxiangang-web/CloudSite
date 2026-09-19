"""Collections application boundary.

Owns Collection/CollectionItem persistence and assembles public/admin views using
only public contracts from Providers, Resources and Catalog.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...catalog.contracts.public import collection_entry_references
from ...providers.contracts.public import enabled_root_ids
from ...resources.contracts.public import ResourceReferenceView, resource_queries
from ..infrastructure.models import Collection, CollectionItem


class CollectionError(Exception):
    pass


class CollectionNotFound(CollectionError):
    def __init__(self, collection_id: int):
        super().__init__(f"collection not found: {collection_id}")
        self.collection_id = collection_id


class CollectionValidationError(CollectionError):
    pass


def _base_payload(row: Collection) -> dict[str, Any]:
    return {
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
    }


def _resource_item_payload(
    resource: ResourceReferenceView,
    *,
    note: str,
) -> dict[str, Any]:
    return {
        "id": resource.id,
        "name": resource.name,
        "parent_id": resource.parent_id,
        "content_type": resource.content_type,
        "extension": resource.extension,
        "mime_type": resource.mime_type,
        "size": resource.size,
        "modified_at": resource.modified_at,
        "thumbnail": "",
        "item_type": "resource",
        "note": note,
    }


async def _items_for(
    state: AsyncSession,
    collection_id: int,
) -> list[CollectionItem]:
    return list(
        (
            await state.scalars(
                select(CollectionItem)
                .where(CollectionItem.collection_id == collection_id)
                .order_by(CollectionItem.sort_order, CollectionItem.id)
            )
        ).all()
    )


async def collection_view(
    state: AsyncSession,
    index: AsyncSession,
    row: Collection,
    *,
    include_items: bool = False,
) -> dict[str, Any]:
    """Public-compatible collection projection used by legacy and public APIs."""

    items = await _items_for(state, row.id)
    resource_ids = [
        item.resource_id
        for item in items
        if item.item_type == "resource" and item.resource_id
    ]
    entry_ids = [
        item.catalog_entry_id
        for item in items
        if item.item_type == "catalog_entry" and item.catalog_entry_id
    ]

    resource_refs = await resource_queries(index).resource_references(
        resource_ids=[rid for rid in resource_ids if rid]
    )
    roots = await enabled_root_ids(state)
    visible_resources = {
        resource_id: resource
        for resource_id, resource in resource_refs.items()
        if resource.status == "active"
        and resource.root_mapping_id is not None
        and resource.root_mapping_id in roots
    }
    visible_entries = await collection_entry_references(
        state,
        entry_ids=[eid for eid in entry_ids if eid],
        published_only=True,
    )

    payload = _base_payload(row)
    payload["item_count"] = (
        sum(1 for rid in resource_ids if rid in visible_resources)
        + sum(1 for eid in entry_ids if eid in visible_entries)
    )

    if include_items:
        serialized: list[dict[str, Any]] = []
        for item in items:
            if item.item_type == "resource" and item.resource_id:
                resource = visible_resources.get(item.resource_id)
                if resource is not None:
                    serialized.append(
                        _resource_item_payload(resource, note=item.note)
                    )
            elif item.item_type == "catalog_entry" and item.catalog_entry_id:
                entry = visible_entries.get(item.catalog_entry_id)
                if entry is not None:
                    serialized.append(
                        {
                            "item_type": "catalog_entry",
                            "catalog_entry_id": entry.entry_id,
                            "id": entry.entry_id,
                            "name": entry.title,
                            "title": entry.title,
                            "summary": entry.summary,
                            "content_type": entry.content_type,
                            "cover_resource_id": entry.cover_resource_id,
                            "note": item.note,
                            "sort_order": item.sort_order,
                        }
                    )
        payload["items"] = serialized
    return payload


async def list_public_collections(
    state: AsyncSession,
    index: AsyncSession,
) -> list[dict[str, Any]]:
    rows = list(
        (
            await state.scalars(
                select(Collection)
                .where(Collection.status == "active")
                .order_by(Collection.sort_order, Collection.name)
            )
        ).all()
    )
    return [await collection_view(state, index, row) for row in rows]


async def list_home_collections(
    state: AsyncSession,
    index: AsyncSession,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """Home-only public collection projection preserving legacy ordering."""

    rows = list(
        (
            await state.scalars(
                select(Collection)
                .where(
                    Collection.visible_on_home.is_(True),
                    Collection.status == "active",
                )
                .order_by(
                    Collection.sort_order,
                    desc(Collection.updated_at),
                )
                .limit(max(int(limit), 0))
            )
        ).all()
    )
    return [
        await collection_view(state, index, row)
        for row in rows
    ]


async def get_public_collection(
    state: AsyncSession,
    index: AsyncSession,
    collection_id: int,
) -> dict[str, Any]:
    row = await state.get(Collection, collection_id)
    if row is None or row.status != "active":
        raise CollectionNotFound(collection_id)
    return await collection_view(state, index, row, include_items=True)


async def list_admin_collections(
    state: AsyncSession,
    index: AsyncSession,
) -> list[dict[str, Any]]:
    rows = list(
        (
            await state.scalars(
                select(Collection).order_by(
                    Collection.sort_order,
                    desc(Collection.updated_at),
                )
            )
        ).all()
    )
    return [await collection_view(state, index, row) for row in rows]


async def get_admin_collection(
    state: AsyncSession,
    index: AsyncSession,
    collection_id: int,
) -> dict[str, Any]:
    row = await state.get(Collection, collection_id)
    if row is None:
        raise CollectionNotFound(collection_id)

    items = await _items_for(state, collection_id)
    resource_ids = [
        item.resource_id
        for item in items
        if item.item_type == "resource" and item.resource_id
    ]
    entry_ids = [
        item.catalog_entry_id
        for item in items
        if item.item_type == "catalog_entry" and item.catalog_entry_id
    ]
    resources = await resource_queries(index).resource_references(
        resource_ids=[rid for rid in resource_ids if rid]
    )
    entries = await collection_entry_references(
        state,
        entry_ids=[eid for eid in entry_ids if eid],
        published_only=False,
    )

    payload = _base_payload(row)
    payload["items"] = []
    for item in items:
        if item.item_type == "resource" and item.resource_id:
            resource = resources.get(item.resource_id)
            active = bool(resource and resource.status == "active")
            payload["items"].append(
                {
                    "item_type": "resource",
                    "resource_id": item.resource_id,
                    "name": resource.name if active and resource else None,
                    "content_type": (
                        resource.content_type if active and resource else ""
                    ),
                    "extension": resource.extension if active and resource else "",
                    "size": resource.size if active and resource else 0,
                    "active": active,
                    "note": item.note,
                    "sort_order": item.sort_order,
                }
            )
        elif item.item_type == "catalog_entry" and item.catalog_entry_id:
            entry = entries.get(item.catalog_entry_id)
            payload["items"].append(
                {
                    "item_type": "catalog_entry",
                    "catalog_entry_id": item.catalog_entry_id,
                    "title": entry.title if entry else None,
                    "content_type": entry.content_type if entry else "",
                    "status": entry.status if entry else None,
                    "active": bool(entry and entry.status == "published"),
                    "note": item.note,
                    "sort_order": item.sort_order,
                }
            )
    return payload


async def create_collection(
    state: AsyncSession,
    *,
    values: dict[str, Any],
) -> int:
    row = Collection(**values)
    state.add(row)
    await state.commit()
    await state.refresh(row)
    return row.id


async def update_collection(
    state: AsyncSession,
    collection_id: int,
    *,
    values: dict[str, Any],
) -> None:
    row = await state.get(Collection, collection_id)
    if row is None:
        raise CollectionNotFound(collection_id)
    for key, value in values.items():
        setattr(row, key, value)
    await state.commit()


async def _validate_resource_ids(
    index: AsyncSession,
    resource_ids: list[str],
) -> None:
    refs = await resource_queries(index).resource_references(
        resource_ids=resource_ids
    )
    missing = [
        resource_id
        for resource_id in resource_ids
        if resource_id not in refs or refs[resource_id].status != "active"
    ]
    if missing:
        raise CollectionValidationError(
            f"资源不存在：{', '.join(missing[:5])}"
        )


async def _validate_entry_ids(
    state: AsyncSession,
    entry_ids: list[str],
) -> None:
    refs = await collection_entry_references(
        state,
        entry_ids=entry_ids,
        published_only=False,
    )
    missing = [entry_id for entry_id in entry_ids if entry_id not in refs]
    if missing:
        raise CollectionValidationError(
            f"Catalog 条目不存在：{', '.join(missing[:5])}"
        )


async def replace_collection_items(
    state: AsyncSession,
    index: AsyncSession,
    collection_id: int,
    *,
    items: list[dict[str, Any]] | None,
    resource_ids: list[str],
) -> int:
    if await state.get(Collection, collection_id) is None:
        raise CollectionNotFound(collection_id)

    normalized: list[CollectionItem] = []
    if items is not None:
        seen: set[tuple[str, str]] = set()
        for position, raw in enumerate(items):
            item_type = str(raw.get("item_type") or "resource")
            note = str(raw.get("note") or "")
            if item_type == "resource":
                resource_id = str(raw.get("resource_id") or "").strip()
                if not resource_id:
                    raise CollectionValidationError(
                        "resource 条目缺少 resource_id"
                    )
                key = ("resource", resource_id)
                if key in seen:
                    continue
                seen.add(key)
                normalized.append(
                    CollectionItem(
                        collection_id=collection_id,
                        item_type="resource",
                        resource_id=resource_id,
                        catalog_entry_id=None,
                        note=note,
                        sort_order=position,
                    )
                )
            elif item_type == "catalog_entry":
                entry_id = str(raw.get("catalog_entry_id") or "").strip()
                if not entry_id:
                    raise CollectionValidationError(
                        "catalog_entry 条目缺少 catalog_entry_id"
                    )
                key = ("catalog_entry", entry_id)
                if key in seen:
                    continue
                seen.add(key)
                normalized.append(
                    CollectionItem(
                        collection_id=collection_id,
                        item_type="catalog_entry",
                        resource_id=None,
                        catalog_entry_id=entry_id,
                        note=note,
                        sort_order=position,
                    )
                )
            else:
                raise CollectionValidationError(
                    f"不支持的合集条目类型：{item_type}"
                )

        normalized_resource_ids = [
            item.resource_id
            for item in normalized
            if item.item_type == "resource" and item.resource_id
        ]
        normalized_entry_ids = [
            item.catalog_entry_id
            for item in normalized
            if item.item_type == "catalog_entry" and item.catalog_entry_id
        ]
        await _validate_resource_ids(
            index,
            [rid for rid in normalized_resource_ids if rid],
        )
        await _validate_entry_ids(
            state,
            [eid for eid in normalized_entry_ids if eid],
        )
    else:
        unique_resource_ids = list(dict.fromkeys(resource_ids))
        await _validate_resource_ids(index, unique_resource_ids)
        normalized = [
            CollectionItem(
                collection_id=collection_id,
                item_type="resource",
                resource_id=resource_id,
                sort_order=position,
            )
            for position, resource_id in enumerate(unique_resource_ids)
        ]

    await state.execute(
        delete(CollectionItem).where(
            CollectionItem.collection_id == collection_id
        )
    )
    state.add_all(normalized)
    await state.commit()
    return len(normalized)


async def delete_collection(
    state: AsyncSession,
    collection_id: int,
) -> None:
    row = await state.get(Collection, collection_id)
    if row is None:
        raise CollectionNotFound(collection_id)
    await state.delete(row)
    await state.commit()


__all__ = [
    "CollectionError",
    "CollectionNotFound",
    "CollectionValidationError",
    "collection_view",
    "list_public_collections",
    "get_public_collection",
    "list_admin_collections",
    "get_admin_collection",
    "create_collection",
    "update_collection",
    "replace_collection_items",
    "delete_collection",
]
