"""browse 路由：全类型浏览，支持类型/状态/分页参数。"""

import math

from fastapi import APIRouter, Query

from ..modules.catalog.contracts.public import published_browse_entries
from ..modules.providers.contracts.public import (
    enabled_content_roots,
    enabled_root_ids,
)
from ..modules.resources.contracts.public import resource_queries

router = APIRouter()

_TYPE_DISPLAY = {
    "software": "软件",
    "image": "图库",
    "video": "视频",
    "document": "教程",
    "file": "文件",
}
_TYPE_ORDER = ("software", "image", "video", "document", "file")


@router.get("/api/browse")
async def browse(
    type: str | None = Query(
        None,
        description="按 content_type 筛选，留空返回全类型",
    ),
    status: str = Query("active", description="资源状态筛选"),
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
):
    """全类型浏览：资源分页 + Catalog 摘要 + 发布根入口。"""

    from ..main import IndexSession, StateSession

    async with IndexSession() as index, StateSession() as state:
        root_ids = await enabled_root_ids(state)
        queries = resource_queries(index)

        counted = await queries.browse_resource_counts(
            enabled_root_ids=root_ids,
            status=status,
            content_types=_TYPE_ORDER,
        )
        counts = {
            content_type: int(counted.get(content_type, 0))
            for content_type in _TYPE_ORDER
        }
        type_entries = [
            {
                "type": content_type,
                "display_name": _TYPE_DISPLAY[content_type],
                "count": counts[content_type],
                "url": f"/browse?type={content_type}",
            }
            for content_type in _TYPE_ORDER
        ]

        resource_page = await queries.browse_resources(
            enabled_root_ids=root_ids,
            status=status,
            content_type=type,
            page=page,
            page_size=page_size,
        )
        catalog_entries = [
            entry.to_dict()
            for entry in await published_browse_entries(
                state,
                content_type=type,
                limit=20,
            )
        ]

        content_roots = []
        if not type:
            content_roots = [
                {
                    "id": root.id,
                    "content_type": root.content_type,
                    "display_name": root.display_name,
                    "home_order": root.home_order,
                    "sort_order": root.sort_order,
                }
                for root in await enabled_content_roots(state)
            ]

        return {
            "type": type,
            "status": status,
            "type_entries": type_entries,
            "counts": counts,
            "items": [item.to_dict() for item in resource_page.items],
            "total": resource_page.total,
            "page": page,
            "page_size": page_size,
            "total_pages": (
                math.ceil(resource_page.total / page_size)
                if resource_page.total
                else 0
            ),
            "catalog_entries": catalog_entries,
            "content_roots": content_roots,
        }
