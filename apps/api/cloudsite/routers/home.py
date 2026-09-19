"""Home HTTP composition: cache + owner-contract aggregation only."""

import time

from fastapi import APIRouter, Request

from ..modules.catalog.contracts.public import (
    featured_cover_resource_ids,
    published_browse_entries,
)
from ..modules.collections.contracts.public import list_home_collections
from ..modules.presentation.contracts.public import public_presentation
from ..modules.providers.contracts.public import (
    enabled_content_roots,
    public_storage_info,
)
from ..modules.resources.contracts.public import resource_queries
from ..schemas import ContentRootListOutput
from ..site import home_site_settings


router = APIRouter()

_home_cache: dict = {"data": None, "fetched_at": 0.0}
_storage_info_cache: dict = {"data": None, "fetched_at": 0.0}
_HOME_CACHE_TTL_SECONDS = 180
STORAGE_INFO_TTL_SECONDS = 600

# Compatibility cache re-exported through cloudsite.main. Provider persistence
# is no longer read here, but admin/setup code still invalidates this marker.
_alist_connection_cache: dict = {"data": None, "fetched_at": 0.0}
_ALIST_CONNECTION_CACHE_TTL_SECONDS = 30

_CONTENT_TYPES = ("software", "image", "video", "document", "file")
_TYPE_DISPLAY = {
    "software": "软件",
    "image": "图库",
    "video": "视频",
    "document": "教程",
    "file": "文件",
}


def invalidate_home_cache() -> None:
    """Drop cached home data after an admin mutation changes its contents."""

    _home_cache["data"] = None
    _home_cache["fetched_at"] = 0.0


def _content_root_payloads(
    roots,
    *,
    resource_counts: dict[int, int],
    folder_counts: dict[int, int],
) -> list[dict]:
    # Legacy response order was sort_order then id. enabled_content_roots()
    # is Home-order aware for the manual-popular strategy, so sort only the
    # serialized root list here.
    ordered = sorted(
        roots,
        key=lambda root: (root.sort_order, root.id),
    )
    return [
        {
            "id": root.id,
            "content_type": root.content_type,
            "display_name": root.display_name,
            "resource_count": resource_counts.get(root.id, 0),
            "folder_count": folder_counts.get(root.id, 0),
            "sort_order": root.sort_order,
        }
        for root in ordered
    ]


@router.get("/api/home")
async def home(request: Request):
    from ..main import IndexSession, StateSession

    now = time.time()
    if (
        _home_cache["data"] is not None
        and (now - _home_cache["fetched_at"]) < _HOME_CACHE_TTL_SECONDS
    ):
        return _home_cache["data"]

    async with StateSession() as state, IndexSession() as index:
        site = await home_site_settings(state)
        roots = await enabled_content_roots(state)
        enabled_ids = {root.id for root in roots}
        popular_strategy = site["popular_strategy"]
        popular_limit = site["popular_limit"]

        featured_ids: list[str] = []
        if popular_strategy == "featured":
            featured_ids = await featured_cover_resource_ids(
                state,
                limit=popular_limit * 2,
            )

        inventory = await resource_queries(index).home_inventory(
            enabled_root_ids=enabled_ids,
            content_types=_CONTENT_TYPES,
            recent_limit=site["recent_limit"],
            popular_limit=popular_limit,
            popular_strategy=popular_strategy,
            featured_resource_ids=featured_ids,
            manual_root_order=tuple(root.id for root in roots),
        )
        collections = await list_home_collections(
            state,
            index,
            limit=site["collection_limit"],
        )
        presentation = await public_presentation(state)
        topic_entries = await published_browse_entries(
            state,
            limit=12,
        )

        content_roots = _content_root_payloads(
            roots,
            resource_counts=inventory.root_resource_counts,
            folder_counts=inventory.root_folder_counts,
        )
        recent = [item.to_dict() for item in inventory.recent]
        popular = [item.to_dict() for item in inventory.popular]
        topics = [
            {
                "entry_id": entry.entry_id,
                "title": entry.title,
                "summary": entry.summary,
                "content_type": entry.content_type,
                "slug": entry.slug,
                "cover_resource_id": entry.cover_resource_id,
            }
            for entry in topic_entries
        ]
        type_entries = [
            {
                "type": content_type,
                "display_name": _TYPE_DISPLAY[content_type],
                "count": inventory.counts.get(content_type, 0),
                "url": f"/browse?type={content_type}",
            }
            for content_type in _CONTENT_TYPES
        ]

        result = {
            "site": {
                "site_name": site["site_name"],
                "home_title": site["home_title"],
                "description": site["description"],
            },
            "content_roots": content_roots,
            "stats": {
                "resource_count": inventory.resource_count,
                "folder_count": inventory.folder_count,
                "total_size": inventory.total_size,
            },
            "recent_resources": recent,
            "counts": inventory.counts,
            "recent": recent,
            "popular": popular,
            "collections": collections,
            "presentation": presentation,
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
    if (
        _storage_info_cache["data"] is not None
        and (now - _storage_info_cache["fetched_at"])
        < STORAGE_INFO_TTL_SECONDS
    ):
        return _storage_info_cache["data"]

    async with StateSession() as state:
        info = await public_storage_info(state)

    _storage_info_cache["data"] = info
    _storage_info_cache["fetched_at"] = now
    return info


@router.get(
    "/api/content-roots",
    response_model=ContentRootListOutput,
)
async def public_content_roots():
    from ..main import IndexSession, StateSession

    async with StateSession() as state, IndexSession() as index:
        roots = await enabled_content_roots(state)
        enabled_ids = {root.id for root in roots}
        resource_counts, folder_counts = (
            await resource_queries(index).root_inventory_counts(
                enabled_root_ids=enabled_ids,
            )
        )
        return {
            "items": _content_root_payloads(
                roots,
                resource_counts=resource_counts,
                folder_counts=folder_counts,
            )
        }
