"""home 路由：首页、存储信息、内容根列表。"""
import time

from fastapi import APIRouter, Request
from sqlalchemy import desc, func, select

from ..alist import AListClient
from ..config import settings
from ..crypto import decrypt_secret
from ..models import (
    AListConnection,
    CatalogEntry,
    Collection,
    ContentRootMapping,
    Folder,
    Resource,
    SitePresentation,
    SiteSettings,
)
from ..schemas import ContentRootListOutput
from ..services.presentation import default_presentation, ordered_blocks, validate_config

router = APIRouter()

_home_cache: dict = {"data": None, "fetched_at": 0.0}
_storage_info_cache: dict = {"data": None, "fetched_at": 0.0}
_HOME_CACHE_TTL_SECONDS = 180
STORAGE_INFO_TTL_SECONDS = 600
_alist_connection_cache: dict = {"data": None, "fetched_at": 0.0}
_ALIST_CONNECTION_CACHE_TTL_SECONDS = 30


def invalidate_home_cache() -> None:
    """Drop cached home data after an admin mutation changes its contents."""
    _home_cache["data"] = None
    _home_cache["fetched_at"] = 0.0


async def _resolve_popular(index, state, scope_filter, strategy: str, limit: int) -> list:
    """根据 popular_strategy 解析热门资源，不再用 size 排序。

    - recent: 按 modified_at desc（最近活跃）
    - featured: catalog_entries.featured=True 优先，不足按 modified_at 补足
    - manual: 按 content_root_mappings.home_order 排序，同组内按 modified_at
    """
    base_query = select(Resource).where(Resource.status == "active", scope_filter)
    if strategy == "featured":
        featured_rows = list((await state.scalars(
            select(CatalogEntry).where(CatalogEntry.featured.is_(True), CatalogEntry.status == "published")
            .order_by(desc(CatalogEntry.published_at)).limit(limit * 2)
        )).all())
        featured_ids = [r.cover_resource_id for r in featured_rows if r.cover_resource_id]
        if featured_ids:
            featured_resources = list((await index.scalars(
                select(Resource).where(Resource.id.in_(featured_ids), Resource.status == "active", scope_filter)
                .order_by(desc(Resource.modified_at)).limit(limit)
            )).all())
            if len(featured_resources) < limit:
                seen_ids = {r.id for r in featured_resources}
                extra_query = base_query.where(Resource.id.notin_(seen_ids)).order_by(desc(Resource.modified_at)).limit(limit - len(featured_resources))
                extra = list((await index.scalars(extra_query)).all())
                return featured_resources + extra
            return featured_resources
        return list((await index.scalars(base_query.order_by(desc(Resource.modified_at)).limit(limit))).all())
    if strategy == "manual":
        manual_roots = list((await state.scalars(
            select(ContentRootMapping).where(ContentRootMapping.enabled.is_(True))
            .order_by(ContentRootMapping.home_order, ContentRootMapping.sort_order, ContentRootMapping.id)
        )).all())
        root_rank = {root.id: idx for idx, root in enumerate(manual_roots)}
        candidate_limit = min(limit * max(len(manual_roots), 1), 200) if manual_roots else limit
        candidates = list((await index.scalars(
            base_query.order_by(desc(Resource.modified_at)).limit(candidate_limit)
        )).all())
        candidates.sort(key=lambda r: (root_rank.get(r.root_mapping_id, 999999), -((r.modified_at.timestamp() if r.modified_at else 0))))
        return candidates[:limit]
    return list((await index.scalars(base_query.order_by(desc(Resource.modified_at)).limit(limit))).all())



@router.get("/api/home")
async def home(request: Request):
    from ..main import StateSession, IndexSession, resource_dict, collection_dict

    now = time.time()
    if _home_cache["data"] is not None and (now - _home_cache["fetched_at"]) < _HOME_CACHE_TTL_SECONDS:
        return _home_cache["data"]
    async with StateSession() as state, IndexSession() as index:
        site = await state.get(SiteSettings, 1)
        root_rows = list((await state.scalars(select(ContentRootMapping).where(ContentRootMapping.enabled.is_(True)).order_by(ContentRootMapping.sort_order, ContentRootMapping.id))).all())
        enabled_ids = {root.id for root in root_rows}
        scope_filter = Resource.root_mapping_id.in_(enabled_ids) if enabled_ids else False
        # 合并 5 个 count 为一条 GROUP BY 查询
        counts_rows = (await index.execute(select(Resource.content_type, func.count()).select_from(Resource).where(Resource.status == "active", scope_filter).group_by(Resource.content_type))).all()
        counts = {ct: 0 for ct in ("software", "image", "video", "document", "file")}
        for row in counts_rows:
            if row[0] in counts:
                counts[row[0]] = int(row[1] or 0)
        recent = list((await index.scalars(select(Resource).where(Resource.status == "active", scope_filter).order_by(desc(Resource.modified_at)).limit(site.recent_limit if site else 6))).all())
        popular_strategy = (site.popular_strategy if site else "recent") or "recent"
        popular_limit = site.popular_limit if site else 6
        popular = await _resolve_popular(index, state, scope_filter, popular_strategy, popular_limit)
        collections = list((await state.scalars(select(Collection).where(Collection.visible_on_home.is_(True), Collection.status == "active").order_by(Collection.sort_order, desc(Collection.updated_at)).limit(site.collection_limit if site else 4))).all())
        # 批量预计算每个 root 的 resource/folder count，避免 N+1 查询
        root_resource_counts = {
            row[0]: int(row[1] or 0)
            for row in (await index.execute(
                select(Resource.root_mapping_id, func.count()).select_from(Resource)
                .where(Resource.status == "active", Resource.root_mapping_id.in_(enabled_ids))
                .group_by(Resource.root_mapping_id)
            )).all()
        } if enabled_ids else {}
        root_folder_counts = {
            row[0]: int(row[1] or 0)
            for row in (await index.execute(
                select(Folder.root_mapping_id, func.count()).select_from(Folder)
                .where(Folder.status == "active", Folder.root_mapping_id.in_(enabled_ids))
                .group_by(Folder.root_mapping_id)
            )).all()
        } if enabled_ids else {}
        content_roots = []
        for root in root_rows:
            content_roots.append({
                "id": root.id,
                "content_type": root.content_type,
                "display_name": root.display_name,
                "resource_count": root_resource_counts.get(root.id, 0),
                "folder_count": root_folder_counts.get(root.id, 0),
                "sort_order": root.sort_order,
            })
        resource_count = int(await index.scalar(select(func.count()).select_from(Resource).where(Resource.status == "active", scope_filter)) or 0)
        folder_count = int(await index.scalar(select(func.count()).select_from(Folder).where(Folder.status == "active", Folder.root_mapping_id.in_(enabled_ids) if enabled_ids else False)) or 0)
        total_size = int(await index.scalar(select(func.coalesce(func.sum(Resource.size), 0)).where(Resource.status == "active", scope_filter)) or 0)
        # B1 站点呈现配置：enabled 时按 home_blocks 顺序渲染区块，否则回退默认
        presentation_row = await state.get(SitePresentation, 1)
        if presentation_row and presentation_row.enabled:
            presentation_cfg = validate_config(presentation_row.preset, presentation_row.theme_tokens_json, presentation_row.navigation_json, presentation_row.home_blocks_json)
            presentation_payload = {
                "enabled": True,
                "preset": presentation_cfg.preset,
                "theme_tokens": presentation_cfg.theme_tokens.model_dump(),
                "navigation": [item.model_dump() for item in presentation_cfg.navigation],
                "ordered_blocks": [block.model_dump() for block in ordered_blocks(presentation_cfg)],
            }
        else:
            _default_cfg = default_presentation()
            presentation_payload = {
                "enabled": False,
                "preset": _default_cfg.preset,
                "theme_tokens": _default_cfg.theme_tokens.model_dump(),
                "navigation": [item.model_dump() for item in _default_cfg.navigation],
                "ordered_blocks": [block.model_dump() for block in ordered_blocks(_default_cfg)],
            }
        # 推荐专题区块数据：已发布 catalog 条目，按 sort_order 与发布时间
        topic_entries = list((await state.scalars(select(CatalogEntry).where(CatalogEntry.status == "published").order_by(CatalogEntry.sort_order, desc(CatalogEntry.published_at)).limit(12))).all())
        topics = [{"entry_id": e.entry_id, "title": e.title, "summary": e.summary, "content_type": e.content_type, "slug": e.slug, "cover_resource_id": e.cover_resource_id} for e in topic_entries]
        _type_display = {"software": "软件", "image": "图库", "video": "视频", "document": "教程", "file": "文件"}
        type_entries = [
            {"type": ct, "display_name": _type_display[ct], "count": counts.get(ct, 0), "url": f"/browse?type={ct}"}
            for ct in ("software", "image", "video", "document", "file")
        ]
        result = {
            "site": {"site_name": site.site_name, "home_title": site.home_title, "description": site.description},
            "content_roots": content_roots,
            "stats": {"resource_count": resource_count, "folder_count": folder_count, "total_size": total_size},
            "recent_resources": [resource_dict(row) for row in recent],
            "counts": counts,
            "recent": [resource_dict(row) for row in recent],
            "popular": [resource_dict(row) for row in popular],
            "collections": [await collection_dict(state, index, row) for row in collections],
            "presentation": presentation_payload,
            "topics": topics,
            "type_entries": type_entries,
            "popular_strategy": popular_strategy,
        }
        _home_cache["data"] = result
        _home_cache["fetched_at"] = now
        return result


@router.get("/api/storage/info")
async def storage_info():
    from ..main import StateSession

    now = time.time()
    if _storage_info_cache["data"] is not None and (now - _storage_info_cache["fetched_at"]) < STORAGE_INFO_TTL_SECONDS:
        return _storage_info_cache["data"]
    async with StateSession() as session:
        connection = await session.get(AListConnection, 1)
    if not connection or not connection.enabled:
        info = {"primary": "网盘", "drives": []}
    else:
        try:
            password = decrypt_secret(connection.password_ciphertext)
            async with AListClient(connection.base_url, connection.username, password) as client:
                info = await client.get_storage_info(connection.base_path or "")
        except Exception:
            info = {"primary": "网盘", "drives": []}
    _storage_info_cache["data"] = info
    _storage_info_cache["fetched_at"] = now
    return info


@router.get("/api/content-roots", response_model=ContentRootListOutput)
async def public_content_roots():
    from ..main import StateSession, IndexSession

    async with StateSession() as state, IndexSession() as index:
        roots = list((await state.scalars(select(ContentRootMapping).where(ContentRootMapping.enabled.is_(True)).order_by(ContentRootMapping.sort_order, ContentRootMapping.id))).all())
        items = []
        for root in roots:
            items.append({
                "id": root.id,
                "content_type": root.content_type,
                "display_name": root.display_name,
                "resource_count": int(await index.scalar(select(func.count()).select_from(Resource).where(Resource.root_mapping_id == root.id, Resource.status == "active")) or 0),
                "folder_count": int(await index.scalar(select(func.count()).select_from(Folder).where(Folder.root_mapping_id == root.id, Folder.status == "active")) or 0),
                "sort_order": root.sort_order,
            })
        return {"items": items}
