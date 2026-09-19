"""Scope-safe FTS-backed search for published Catalog entries (D1).

读路径：
1. consume_catalog_search_outbox 同步消费 pending 投影行（确保看到最新写入）。
2. catalog_search_fts MATCH 召回候选 entry_id（含别名/标签/平台文本）。
3. content_type/tag/platform 过滤。
4. 每个候选通过 catalog_entry_view(public=True) fail-closed 实时校验 availability
   ——权限过滤不依赖 FTS 删除，FTS 残有旧条目也会被实时校验丢弃。
5. 排序分页，返回 match_type 与无结果 suggestion。

旧 /api/search 契约零改动；本模块仅服务 /api/catalog/search。
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    CatalogAsset,
    CatalogEntry,
    CatalogRelease,
    CatalogTag,
    CatalogTagAssignment,
)
from .catalog_search_projection import (
    catalog_search_fts_match,
    consume_catalog_search_outbox,
)
from ..modules.catalog.contracts.public import catalog_entry_view


def normalize_catalog_query(value: str) -> str:
    return " ".join(value.strip().split())


def _contains(haystack: str, needle: str) -> bool:
    return needle in haystack.casefold()


_NO_RESULT_SUGGESTION = "未找到匹配的资源条目，可尝试更换关键词、清除筛选条件，或在文件搜索中查找具体文件。"


async def search_published_catalog(
    state: AsyncSession,
    index: AsyncSession,
    *,
    query: str,
    page: int = 1,
    page_size: int = 24,
    content_type: str | None = None,
    tag: str | None = None,
    platform: str | None = None,
) -> dict[str, Any]:
    """Search published entries via FTS projection and fail closed against live scope."""
    normalized = normalize_catalog_query(query)
    if not normalized:
        raise ValueError("catalog search query is empty")
    if len(normalized) > 200:
        raise ValueError("catalog search query is too long")
    if page < 1 or page_size < 1 or page_size > 100:
        raise ValueError("invalid catalog search pagination")

    # 先消费 outbox，确保投影反映最新 catalog 写操作。
    await consume_catalog_search_outbox(state, index)

    # FTS 召回候选 entry_id（含 content_type 过滤）。
    candidates = await catalog_search_fts_match(
        index, query=normalized, content_type=content_type, limit=500
    )
    if not candidates:
        return _page([], normalized, page, page_size, content_type, tag, platform)

    entry_ids = [row["entry_id"] for row in candidates]
    entries = list(
        (
            await state.scalars(
                select(CatalogEntry).where(
                    CatalogEntry.entry_id.in_(entry_ids),
                    CatalogEntry.status == "published",
                )
            )
        ).all()
    )
    if not entries:
        return _page([], normalized, page, page_size, content_type, tag, platform)

    # 批量加载 releases/assets/tags 用于过滤与排名。
    visible_ids = [entry.entry_id for entry in entries]
    releases = list(
        (
            await state.scalars(
                select(CatalogRelease).where(CatalogRelease.entry_id.in_(visible_ids))
            )
        ).all()
    )
    releases_by_entry: dict[str, list[CatalogRelease]] = defaultdict(list)
    for release in releases:
        releases_by_entry[release.entry_id].append(release)

    release_ids = [release.release_id for release in releases]
    assets = (
        list(
            (
                await state.scalars(
                    select(CatalogAsset).where(CatalogAsset.release_id.in_(release_ids))
                )
            ).all()
        )
        if release_ids
        else []
    )
    assets_by_release: dict[str, list[CatalogAsset]] = defaultdict(list)
    for asset in assets:
        assets_by_release[asset.release_id].append(asset)

    tag_rows = list(
        (
            await state.execute(
                select(CatalogTagAssignment.target_id, CatalogTag)
                .join(CatalogTag, CatalogTag.tag_id == CatalogTagAssignment.tag_id)
                .where(
                    CatalogTagAssignment.target_type == "entry",
                    CatalogTagAssignment.target_id.in_(visible_ids),
                )
            )
        ).all()
    )
    tags_by_entry: dict[str, list[CatalogTag]] = defaultdict(list)
    for entry_id, tag_row in tag_rows:
        tags_by_entry[entry_id].append(tag_row)

    needle = normalized.casefold()
    tag_filter = tag.casefold() if tag else None
    platform_filter = platform.casefold() if platform else None

    # 候选 entry_id 集合用于排序稳定（FTS 召回顺序）。
    candidate_order = {row["entry_id"]: idx for idx, row in enumerate(candidates)}
    ranked: list[tuple[int, int, CatalogEntry]] = []
    for entry in entries:
        entry_tags = tags_by_entry[entry.entry_id]
        entry_releases = releases_by_entry[entry.entry_id]
        entry_assets = [
            asset
            for release in entry_releases
            for asset in assets_by_release[release.release_id]
        ]
        if tag_filter and not any(
            item.slug.casefold() == tag_filter for item in entry_tags
        ):
            continue
        if platform_filter and not any(
            (asset.platform or "unknown").casefold() == platform_filter
            for asset in entry_assets
        ):
            continue

        title = entry.title.casefold()
        metadata = " ".join(
            [
                entry.slug,
                entry.summary,
                entry.description,
                *(item.slug for item in entry_tags),
                *(item.display_name for item in entry_tags),
                *(release.slug for release in entry_releases),
                *(release.title for release in entry_releases),
                *(release.channel or "unknown" for release in entry_releases),
                *(asset.display_name for asset in entry_assets),
                *(asset.slug for asset in entry_assets),
                *(asset.platform or "unknown" for asset in entry_assets),
                *(asset.architecture or "unknown" for asset in entry_assets),
                *(asset.package_type or "unknown" for asset in entry_assets),
            ]
        )
        if title == needle:
            rank = 400
        elif title.startswith(needle):
            rank = 300
        elif needle in title:
            rank = 200
        elif _contains(metadata, needle):
            rank = 100
        else:
            # FTS 命中但内存 metadata 未命中（例如分词差异），仍保留为最低 rank。
            rank = 50
        ranked.append((rank, candidate_order.get(entry.entry_id, 0), entry))

    ranked.sort(
        key=lambda item: (-item[0], item[1], item[2].sort_order, item[2].title.casefold())
    )
    visible: list[dict[str, Any]] = []
    for rank, _order, entry in ranked:
        view = await catalog_entry_view(state, index, entry, public=True)
        if view["availability"] != "available":
            continue
        if platform_filter and not any(
            asset["availability"] == "available"
            and asset["platform"].casefold() == platform_filter
            for release in view["releases"]
            for asset in release["assets"]
        ):
            continue
        view["match_type"] = {
            400: "exact",
            300: "prefix",
            200: "title",
            100: "metadata",
            50: "fts",
        }[rank]
        visible.append(view)
    return _page(visible, normalized, page, page_size, content_type, tag, platform)


def _page(
    rows: list[dict[str, Any]],
    query: str,
    page: int,
    page_size: int,
    content_type: str | None,
    tag: str | None,
    platform: str | None,
) -> dict[str, Any]:
    total = len(rows)
    start = (page - 1) * page_size
    items = rows[start : start + page_size]
    return {
        "query": query,
        "filters": {
            "content_type": content_type,
            "tag": tag,
            "platform": platform,
        },
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": (total + page_size - 1) // page_size if total else 0,
        "suggestion": _NO_RESULT_SUGGESTION if total == 0 else None,
    }
