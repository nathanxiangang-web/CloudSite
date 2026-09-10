"""B2 公开发布范围：区分登录可见与公开可见，生成独立公开 DTO。

CatalogEntry.publicly_visible 区分：
- 登录可见（默认 False）：已登录用户可在目录中看到，不出现在 sitemap.xml
- 公开可见（管理员显式公开 True）：出现在 sitemap.xml，公开页面生成独立 DTO

公开 DTO 不含管理敏感信息（revision、内部 status、sort_order、cover_resource_id）。
撤回公开时清除首页缓存与站点地图缓存条目。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import CatalogEntry


def is_publicly_visible(entry: CatalogEntry) -> bool:
    """条目是否对公开访客可见（已发布且显式公开）。"""
    return bool(entry.publicly_visible) and entry.status == "published"


def public_entry_dto(entry: CatalogEntry) -> dict:
    """生成独立公开 DTO，不含管理敏感信息。

    仅包含公开页面所需字段：entry_id、title、summary、content_type、slug、
    published_at。排除 revision、内部 status、sort_order、cover_resource_id、
    created_at、updated_at 等管理字段。
    """
    return {
        "entry_id": entry.entry_id,
        "title": entry.title,
        "summary": entry.summary or "",
        "description": entry.description or "",
        "content_type": entry.content_type,
        "slug": entry.slug,
        "published_at": entry.published_at.isoformat() if entry.published_at else None,
        "publicly_visible": True,
    }


async def list_public_entries(state: AsyncSession) -> list[CatalogEntry]:
    """返回所有公开可见且已发布的条目，按 sort_order 排序。"""
    rows = await state.scalars(
        select(CatalogEntry)
        .where(CatalogEntry.publicly_visible.is_(True), CatalogEntry.status == "published")
        .order_by(CatalogEntry.sort_order, CatalogEntry.title)
    )
    return list(rows.all())


async def set_publicly_visible(state: AsyncSession, entry_id: str, visible: bool) -> CatalogEntry | None:
    """设置条目公开可见性，返回更新后的条目或 None。"""
    entry = await state.get(CatalogEntry, entry_id)
    if entry is None:
        return None
    entry.publicly_visible = bool(visible)
    return entry


def sitemap_entry_url(entry: CatalogEntry, base_url: str) -> str:
    """生成条目在 sitemap 中的公开 URL。"""
    return f"{base_url.rstrip('/')}/catalog/{entry.entry_id}"


def build_sitemap_xml(entries: list[CatalogEntry], base_url: str) -> str:
    """构建 sitemap.xml 文档，只含公开可见条目。"""
    urls: list[str] = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for entry in entries:
        if not is_publicly_visible(entry):
            continue
        loc = sitemap_entry_url(entry, base_url)
        lastmod = entry.published_at.strftime("%Y-%m-%d") if entry.published_at else now
        urls.append(
            "  <url>\n"
            f"    <loc>{loc}</loc>\n"
            f"    <lastmod>{lastmod}</lastmod>\n"
            f"    <changefreq>weekly</changefreq>\n"
            "    <priority>0.8</priority>\n"
            "  </url>"
        )
    body = "\n".join(urls)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{body}\n"
        "</urlset>"
    )


_sitemap_cache: dict[str, object] = {"data": None, "fetched_at": 0.0}


def invalidate_sitemap_cache() -> None:
    """清除站点地图缓存（撤回公开时调用）。"""
    _sitemap_cache["data"] = None
    _sitemap_cache["fetched_at"] = 0.0
