"""search 路由：搜索。"""
import math

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from ..indexer import log_operation
from ..models import Folder, Resource
from ..schemas import SearchOutput
from ..search import (
    SEARCH_OBJECT_TYPES,
    SEARCH_SORTS,
    SEARCH_TYPES,
    classify_match,
    normalize_search_query,
    search_index,
)
from ..services.resources import breadcrumbs_batch, folder_dict, resource_dict
from ..shares.service import enabled_root_ids

router = APIRouter()


@router.get("/api/search", response_model=SearchOutput)
async def search(
    q: str = "",
    resource_type: str | None = Query(default=None, alias="type"),
    object_type: str = "all",
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    sort: str = "relevance",
):
    from ..main import IndexSession, StateSession

    normalized = normalize_search_query(q)
    if not normalized:
        raise HTTPException(400, {"code": "SRCH-001", "message": "搜索关键词为空"})
    if len(normalized) > 200:
        raise HTTPException(400, {"code": "SRCH-002", "message": "搜索关键词过长"})
    if resource_type is not None and resource_type not in SEARCH_TYPES:
        raise HTTPException(400, {"code": "SRCH-004", "message": "资源类型无效"})
    if object_type not in SEARCH_OBJECT_TYPES or sort not in SEARCH_SORTS:
        raise HTTPException(400, {"code": "SRCH-004", "message": "搜索参数无效"})
    try:
        async with IndexSession() as session, StateSession() as state:
            enabled_ids = await enabled_root_ids(state)
            candidates, total = await search_index(session, normalized, resource_type, object_type, page, page_size, sort, enabled_root_ids=enabled_ids)
            resource_ids = [row["object_id"] for row in candidates if row["object_type"] == "resource"]
            folder_ids = [row["object_id"] for row in candidates if row["object_type"] == "folder"]
            resources_by_id = {
                row.id: row for row in (await session.scalars(select(Resource).where(Resource.id.in_(resource_ids), Resource.status == "active"))).all()
            } if resource_ids else {}
            folders_by_id = {
                row.id: row for row in (await session.scalars(select(Folder).where(Folder.id.in_(folder_ids), Folder.status == "active"))).all()
            } if folder_ids else {}
            # 批量加载 resource 的 parent folder（用于 resource_dict）+ 收集 breadcrumbs 起始 id
            parent_ids = {row.parent_id for row in resources_by_id.values() if row.parent_id}
            parents_by_id = {
                row.id: row for row in (await session.scalars(select(Folder).where(Folder.id.in_(parent_ids), Folder.status == "active"))).all()
            } if parent_ids else {}
            breadcrumb_map = await breadcrumbs_batch(session, list(parent_ids) + folder_ids)
            items = []
            for candidate in candidates:
                if candidate["object_type"] == "resource":
                    row = resources_by_id.get(candidate["object_id"])
                    if not row:
                        continue
                    parent = parents_by_id.get(row.parent_id or "")
                    payload = resource_dict(row, parent)
                    payload.update({
                        "object_type": "resource",
                        "breadcrumbs": breadcrumb_map.get(row.parent_id, []) if row.parent_id else [],
                        "child_folder_count": 0,
                        "resource_count": 0,
                        "match_type": classify_match(row.name, normalized),
                    })
                else:
                    row = folders_by_id.get(candidate["object_id"])
                    if not row:
                        continue
                    payload = folder_dict(row)
                    payload.update({
                        "object_type": "folder",
                        "extension": "",
                        "size": None,
                        "parent": None,
                        "breadcrumbs": breadcrumb_map.get(row.id, []),
                        "thumbnail": "",
                        "match_type": classify_match(row.name, normalized),
                    })
                items.append(payload)
            from ..services.metrics import EVENT_SEARCH_PERFORMED, try_record
            await try_record(state, EVENT_SEARCH_PERFORMED, {
                "result_count": total,
                "raw_query": normalized,
            })
            return {
                "query": normalized,
                "filters": {"type": resource_type, "object_type": object_type, "sort": sort},
                "items": items,
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": math.ceil(total / page_size) if total else 0,
            }
    except HTTPException:
        raise
    except Exception as exc:
        await log_operation("search", "query_failed", type(exc).__name__, level="ERROR")
        raise HTTPException(503, {"code": "SRCH-003", "message": "搜索索引暂时不可用"}) from exc
