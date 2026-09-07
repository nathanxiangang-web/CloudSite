"""resources 服务：资源/文件夹序列化与面包屑辅助函数。"""
from ..models import Folder, Resource


def resource_dict(row: Resource, parent: Folder | None = None) -> dict:
    payload = {
        "id": row.id,
        "name": row.name,
        "parent_id": row.parent_id,
        "content_type": row.content_type,
        "extension": row.extension,
        "mime_type": row.mime_type,
        "size": row.size,
        "modified_at": row.modified_at,
        "thumbnail": "",
    }
    if parent:
        payload["parent"] = {"id": parent.id, "name": parent.name}
    return payload


def folder_dict(row: Folder, include_path: bool = False) -> dict:
    payload = {
        "id": row.id,
        "name": row.name,
        "parent_id": row.parent_id,
        "content_type": row.content_type,
        "depth": row.depth,
        "child_folder_count": row.child_folder_count,
        "resource_count": row.resource_count,
        "modified_at": row.modified_at,
    }
    if include_path:
        payload["path"] = row.path
        payload["root_mapping_id"] = row.root_mapping_id
        payload["status"] = row.status
        payload["indexed_at"] = row.indexed_at
    return payload


def breadcrumbs_for(folder: Folder | None, folders_by_id: dict[str, Folder]) -> list[dict]:
    items: list[dict] = []
    current = folder
    visited: set[str] = set()
    while current and current.id not in visited:
        visited.add(current.id)
        items.append({"id": current.id, "name": current.name})
        current = folders_by_id.get(current.parent_id or "")
    return list(reversed(items))


async def breadcrumbs_for_folder(session, folder: Folder | None) -> list[dict]:
    """沿 parent_id 链向上查询祖先，仅加载祖先节点而非全表 folders。"""
    items: list[dict] = []
    current = folder
    visited: set[str] = set()
    while current and current.id not in visited:
        visited.add(current.id)
        items.append({"id": current.id, "name": current.name})
        if not current.parent_id:
            break
        current = await session.get(Folder, current.parent_id)
    return list(reversed(items))


async def breadcrumbs_batch(session, folder_ids: list[str]) -> dict[str, list[dict]]:
    """批量解析多个文件夹的祖先链，共享缓存避免重复查询与全表加载。"""
    cache: dict[str, Folder] = {}
    result: dict[str, list[dict]] = {}
    for start_id in folder_ids:
        if not start_id or start_id in result:
            continue
        chain: list[dict] = []
        current_id: str | None = start_id
        visited: set[str] = set()
        while current_id and current_id not in visited:
            visited.add(current_id)
            folder = cache.get(current_id)
            if folder is None:
                folder = await session.get(Folder, current_id)
                if folder is None:
                    break
                cache[current_id] = folder
            chain.append({"id": folder.id, "name": folder.name})
            current_id = folder.parent_id
        result[start_id] = list(reversed(chain))
    return result