"""Search-owned persistence for Catalog FTS projection state."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ...catalog.contracts.public import CatalogSearchDocument


_CATALOG_FTS_INSERT_SQL = text(
    "INSERT INTO catalog_search_fts("
    "entry_id, content_type, title, summary, description, aliases, tags, platforms"
    ") VALUES ("
    ":entry_id, :content_type, :title, :summary, :description, :aliases, :tags, :platforms"
    ")"
)
_CATALOG_FTS_DELETE_SQL = text(
    "DELETE FROM catalog_search_fts WHERE entry_id = :entry_id"
)
_PROJECTION_STATE_UPSERT_SQL = text(
    "INSERT INTO catalog_search_projection_state("
    "entry_id, applied_revision, updated_at"
    ") VALUES (:entry_id, :applied_revision, :updated_at) "
    "ON CONFLICT(entry_id) DO UPDATE SET "
    "applied_revision = :applied_revision, updated_at = :updated_at"
)
_PROJECTION_STATE_GET_SQL = text(
    "SELECT applied_revision FROM catalog_search_projection_state "
    "WHERE entry_id = :entry_id"
)
_FTS_TOKEN_RE = re.compile(r"[0-9A-Za-z\u0080-\uffff]+")


def _build_catalog_fts_query(value: str) -> str:
    tokens = _FTS_TOKEN_RE.findall(value)[:8]
    return " AND ".join(
        f'"{token.replace(chr(34), chr(34) * 2)}"*'
        for token in tokens
    )


async def catalog_projection_revision(
    index: AsyncSession,
    *,
    entry_id: str,
) -> int | None:
    value = (
        await index.execute(
            _PROJECTION_STATE_GET_SQL,
            {"entry_id": entry_id},
        )
    ).scalar_one_or_none()
    return int(value) if value is not None else None


async def upsert_catalog_search_document(
    index: AsyncSession,
    document: CatalogSearchDocument,
) -> None:
    await index.execute(
        _CATALOG_FTS_DELETE_SQL,
        {"entry_id": document.entry_id},
    )
    await index.execute(
        _CATALOG_FTS_INSERT_SQL,
        {
            "entry_id": document.entry_id,
            "content_type": document.content_type,
            "title": document.title,
            "summary": document.summary,
            "description": document.description,
            "aliases": document.aliases,
            "tags": document.tags,
            "platforms": document.platforms,
        },
    )


async def delete_catalog_search_document(
    index: AsyncSession,
    *,
    entry_id: str,
) -> None:
    await index.execute(
        _CATALOG_FTS_DELETE_SQL,
        {"entry_id": entry_id},
    )


async def set_catalog_projection_revision(
    index: AsyncSession,
    *,
    entry_id: str,
    revision: int,
    updated_at: datetime,
) -> None:
    await index.execute(
        _PROJECTION_STATE_UPSERT_SQL,
        {
            "entry_id": entry_id,
            "applied_revision": revision,
            "updated_at": updated_at,
        },
    )


async def clear_catalog_search_projection(
    index: AsyncSession,
) -> None:
    await index.execute(text("DELETE FROM catalog_search_fts"))
    await index.execute(text("DELETE FROM catalog_search_projection_state"))


async def catalog_search_fts_match(
    index: AsyncSession,
    *,
    query: str,
    content_type: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    normalized = " ".join(query.strip().split())
    if not normalized:
        return []
    fts_query = _build_catalog_fts_query(normalized)
    if not fts_query:
        return []

    sql = text(
        "SELECT entry_id, content_type, title FROM catalog_search_fts "
        "WHERE catalog_search_fts MATCH :fts_query"
        + (" AND content_type = :content_type" if content_type else "")
        + " LIMIT :limit"
    )
    params: dict[str, Any] = {
        "fts_query": fts_query,
        "limit": limit,
    }
    if content_type:
        params["content_type"] = content_type
    rows = (await index.execute(sql, params)).all()
    return [
        {
            "entry_id": row[0],
            "content_type": row[1],
            "title": row[2],
        }
        for row in rows
    ]


__all__ = [
    "catalog_projection_revision",
    "catalog_search_fts_match",
    "clear_catalog_search_projection",
    "delete_catalog_search_document",
    "set_catalog_projection_revision",
    "upsert_catalog_search_document",
]
