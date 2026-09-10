"""browse 路由：全类型浏览，支持类型/状态/分页参数。"""
import math

from fastapi import APIRouter, Query
from sqlalchemy import desc, func, select

from ..models import CatalogEntry, ContentRootMapping, Resource
from ..services.resources import resource_dict
from ..shares.service import enabled_root_ids

router = APIRouter()

_TYPE_DISPLAY = {"software": "软件", "image": "图库", "video": "视频", "document": "教程", "file": "文件"}
_TYPE_ORDER = ("software", "image", "video", "document", "file")


@router.get("/api/browse")
async def browse(
    type: str | None = Query(None, description="按 content_type 筛选，留空返回全类型"),
    status: str = Query("active", description="资源状态筛选"),
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
):
    """全类型浏览：返回按类型分组的资源列表 + CatalogEntry 列表。

    - type 留空：返回各类型计数与入口、最近资源分页、已发布 catalog 条目
    - type 指定：返回该类型资源分页 + 该类型 catalog 条目
    """
    from ..main import IndexSession, StateSession

    async with IndexSession() as index, StateSession() as state:
        enabled_ids = await enabled_root_ids(state)
        scope_filter = Resource.root_mapping_id.in_(enabled_ids) if enabled_ids else False

        counts_rows = (await index.execute(
            select(Resource.content_type, func.count()).select_from(Resource)
            .where(Resource.status == status, scope_filter)
            .group_by(Resource.content_type)
        )).all()
        counts = {ct: 0 for ct in _TYPE_ORDER}
        for row in counts_rows:
            if row[0] in counts:
                counts[row[0]] = int(row[1] or 0)

        type_entries = [
            {"type": ct, "display_name": _TYPE_DISPLAY[ct], "count": counts.get(ct, 0), "url": f"/browse?type={ct}"}
            for ct in _TYPE_ORDER
        ]

        query = select(Resource).where(Resource.status == status, scope_filter)
        count_query = select(func.count()).select_from(Resource).where(Resource.status == status, scope_filter)
        if type:
            query = query.where(Resource.content_type == type)
            count_query = count_query.where(Resource.content_type == type)

        total = int(await index.scalar(count_query) or 0)
        rows = list((await index.scalars(
            query.order_by(desc(Resource.modified_at), Resource.id)
            .offset((page - 1) * page_size).limit(page_size)
        )).all())
        items = [resource_dict(row) for row in rows]

        catalog_query = select(CatalogEntry).where(CatalogEntry.status == "published")
        if type:
            catalog_query = catalog_query.where(CatalogEntry.content_type == type)
        catalog_rows = list((await state.scalars(
            catalog_query.order_by(CatalogEntry.sort_order, desc(CatalogEntry.published_at)).limit(20)
        )).all())
        catalog_entries = [
            {
                "entry_id": e.entry_id,
                "title": e.title,
                "summary": e.summary,
                "content_type": e.content_type,
                "slug": e.slug,
                "cover_resource_id": e.cover_resource_id,
                "featured": bool(e.featured),
            }
            for e in catalog_rows
        ]

        root_rows = list((await state.scalars(
            select(ContentRootMapping).where(ContentRootMapping.enabled.is_(True))
            .order_by(ContentRootMapping.home_order, ContentRootMapping.sort_order, ContentRootMapping.id)
        )).all()) if not type else []
        content_roots = [
            {
                "id": root.id,
                "content_type": root.content_type,
                "display_name": root.display_name,
                "home_order": root.home_order,
                "sort_order": root.sort_order,
            }
            for root in root_rows
        ]

        return {
            "type": type,
            "status": status,
            "type_entries": type_entries,
            "counts": counts,
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": math.ceil(total / page_size) if total else 0,
            "catalog_entries": catalog_entries,
            "content_roots": content_roots,
        }
