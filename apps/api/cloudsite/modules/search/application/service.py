"""Application workflows for public Search and rebuild."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from cloudsite.platform.db import index_session, state_session

from ...resources.contracts.public import (
    SearchFolderView,
    SearchResourceView,
    resource_queries,
)
from ..domain.query import (
    SearchCandidate,
    classify_match,
)
from ..infrastructure.fts_repository import (
    rebuild_search_index,
    search_candidates,
    search_index_is_dirty,
    set_search_index_dirty,
)


@dataclass(frozen=True, slots=True)
class SearchRebuildResult:
    indexed: int
    folders: int
    resources: int


def _timestamp(value: datetime | None) -> float:
    if value is None:
        return 0.0
    return value.timestamp()


def _resource_payload(
    row: SearchResourceView,
    *,
    query: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": row.id,
        "name": row.name,
        "parent_id": row.parent_id,
        "content_type": row.content_type,
        "extension": row.extension,
        "mime_type": row.mime_type,
        "size": row.size,
        "modified_at": row.modified_at,
        "thumbnail": "",
        "object_type": "resource",
        "breadcrumbs": [
            item.to_dict()
            for item in row.breadcrumbs
        ],
        "child_folder_count": 0,
        "resource_count": 0,
        "match_type": classify_match(row.name, query),
    }
    if row.parent is not None:
        payload["parent"] = row.parent.to_dict()
    return payload


def _folder_payload(
    row: SearchFolderView,
    *,
    query: str,
) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "parent_id": row.parent_id,
        "content_type": row.content_type,
        "depth": row.depth,
        "child_folder_count": row.child_folder_count,
        "resource_count": row.resource_count,
        "modified_at": row.modified_at,
        "object_type": "folder",
        "extension": "",
        "size": None,
        "parent": None,
        "breadcrumbs": [
            item.to_dict()
            for item in row.breadcrumbs
        ],
        "thumbnail": "",
        "match_type": classify_match(row.name, query),
    }


async def search_public_resources(
    index: AsyncSession,
    *,
    query: str,
    resource_type: str | None,
    object_type: str,
    page: int,
    page_size: int,
    sort: str,
    enabled_root_ids: set[int],
) -> dict[str, Any]:
    if not enabled_root_ids:
        return {
            "query": query,
            "filters": {
                "type": resource_type,
                "object_type": object_type,
                "sort": sort,
            },
            "items": [],
            "page": page,
            "page_size": page_size,
            "total": 0,
            "total_pages": 0,
        }

    candidates = await search_candidates(
        index,
        query=query,
        content_type=resource_type,
        object_type=object_type,
    )
    resource_ids = [
        item.object_id
        for item in candidates
        if item.object_type == "resource"
    ]
    folder_ids = [
        item.object_id
        for item in candidates
        if item.object_type == "folder"
    ]
    hydrated = await resource_queries(index).search_objects(
        resource_ids=resource_ids,
        folder_ids=folder_ids,
        enabled_root_ids=enabled_root_ids,
    )
    resources = {
        row.id: row
        for row in hydrated.resources
    }
    folders = {
        row.id: row
        for row in hydrated.folders
    }

    visible: list[
        tuple[SearchCandidate, SearchResourceView | SearchFolderView]
    ] = []
    for candidate in candidates:
        if candidate.object_type == "resource":
            row = resources.get(candidate.object_id)
        else:
            row = folders.get(candidate.object_id)
        if row is not None:
            visible.append((candidate, row))

    if sort == "relevance":
        visible.sort(
            key=lambda item: (
                -item[0].relevance,
                item[0].name.casefold(),
                item[0].object_id,
            )
        )
    elif sort == "modified_at":
        visible.sort(
            key=lambda item: (
                item[1].modified_at is None,
                -_timestamp(item[1].modified_at),
                item[0].name.casefold(),
                item[0].object_id,
            )
        )
    elif sort == "name":
        visible.sort(
            key=lambda item: (
                item[0].name.casefold(),
                item[0].object_id,
            )
        )
    elif sort == "size":
        visible.sort(
            key=lambda item: (
                not isinstance(item[1], SearchResourceView),
                -(
                    item[1].size
                    if isinstance(item[1], SearchResourceView)
                    else 0
                ),
                item[0].name.casefold(),
                item[0].object_id,
            )
        )

    total = len(visible)
    start = (page - 1) * page_size
    selected = visible[start:start + page_size]
    items: list[dict[str, Any]] = []
    for _candidate, row in selected:
        if isinstance(row, SearchResourceView):
            items.append(_resource_payload(row, query=query))
        else:
            items.append(_folder_payload(row, query=query))

    return {
        "query": query,
        "filters": {
            "type": resource_type,
            "object_type": object_type,
            "sort": sort,
        },
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": math.ceil(total / page_size) if total else 0,
    }


async def rebuild_public_search_index(
    state: AsyncSession,
    index: AsyncSession,
) -> SearchRebuildResult:
    await set_search_index_dirty(state, True)
    documents = await resource_queries(index).search_documents()
    indexed = await rebuild_search_index(index, documents)
    await index.commit()
    await set_search_index_dirty(state, False)
    return SearchRebuildResult(
        indexed=indexed,
        folders=sum(
            1
            for item in documents
            if item.object_type == "folder"
        ),
        resources=sum(
            1
            for item in documents
            if item.object_type == "resource"
        ),
    )


async def recover_search_index_if_dirty() -> int:
    """Rebuild resource search from authoritative inventory when marked dirty.

    Startup callers keep the historical zero-argument API, while Search owns
    dirty-state inspection and rebuild orchestration through platform DB and
    Resources contracts. A failed rebuild leaves the dirty marker set.
    """
    async with state_session() as state:
        if not await search_index_is_dirty(state):
            return 0
        async with index_session() as index:
            result = await rebuild_public_search_index(state, index)
            return result.indexed


__all__ = [
    "SearchRebuildResult",
    "search_public_resources",
    "rebuild_public_search_index",
    "recover_search_index_if_dirty",
]
