"""SQLite FTS persistence adapter owned by Search."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ...catalog.contracts.public import CatalogSearchDocument
from ...resources.contracts.public import SearchDocumentView
from ..domain.query import (
    SearchCandidate,
    build_fts_query,
    escape_like,
)

SEARCH_INDEX_DIRTY_KEY = "search_index_dirty"


async def search_candidates(
    session: AsyncSession,
    *,
    query: str,
    content_type: str | None,
    object_type: str,
) -> list[SearchCandidate]:
    escaped = escape_like(query)
    parameters: dict[str, object] = {
        "query_lower": query.casefold(),
        "like": f"%{escaped}%",
        "prefix": f"{escaped}%",
        "content_type": content_type,
        "object_type": None if object_type == "all" else object_type,
    }
    fts_query = build_fts_query(query)
    fts_clause = (
        " OR rowid IN ("
        "SELECT rowid FROM search_fts "
        "WHERE search_fts MATCH :fts_query)"
        if fts_query
        else ""
    )
    if fts_query:
        parameters["fts_query"] = fts_query

    statement = text(
        f"""
        SELECT object_id, object_type, name, extension, content_type,
               CASE
                 WHEN lower(name) = :query_lower THEN 400
                 WHEN name LIKE :prefix ESCAPE '\\' THEN 300
                 WHEN name LIKE :like ESCAPE '\\' THEN 200
                 ELSE 100
               END AS relevance
        FROM search_fts
        WHERE (:content_type IS NULL OR content_type = :content_type)
          AND (:object_type IS NULL OR object_type = :object_type)
          AND (
            name LIKE :like ESCAPE '\\'
            OR extension LIKE :like ESCAPE '\\'
            OR description LIKE :like ESCAPE '\\'
            OR tags LIKE :like ESCAPE '\\'
            OR breadcrumb_text LIKE :like ESCAPE '\\'
            {fts_clause}
          )
        ORDER BY relevance DESC, name COLLATE NOCASE ASC, object_id ASC
        """
    )
    rows = (await session.execute(statement, parameters)).mappings().all()
    return [
        SearchCandidate(
            object_id=str(row["object_id"]),
            object_type=str(row["object_type"]),
            name=str(row["name"]),
            extension=str(row["extension"] or ""),
            content_type=str(row["content_type"]),
            relevance=int(row["relevance"] or 0),
        )
        for row in rows
    ]


async def rebuild_search_index(
    session: AsyncSession,
    documents: Iterable[SearchDocumentView],
) -> int:
    await session.execute(text("DELETE FROM search_fts"))
    statement = text(
        "INSERT INTO search_fts("
        "object_id, object_type, name, extension, content_type, "
        "description, tags, breadcrumb_text"
        ") VALUES ("
        ":id, :object_type, :name, :extension, :content_type, "
        ":description, :tags, :breadcrumb_text"
        ")"
    )
    rows = [
        {
            "id": item.object_id,
            "object_type": item.object_type,
            "name": item.name,
            "extension": item.extension,
            "content_type": item.content_type,
            "description": "",
            "tags": "",
            "breadcrumb_text": item.breadcrumb_text,
        }
        for item in documents
    ]
    if rows:
        await session.execute(statement, rows)
    return len(rows)


async def search_index_is_dirty(state: AsyncSession) -> bool:
    """Return whether the resource FTS index is marked dirty."""
    value = (
        await state.execute(
            text(
                "SELECT value FROM system_settings "
                "WHERE key = :key"
            ),
            {"key": SEARCH_INDEX_DIRTY_KEY},
        )
    ).scalar_one_or_none()
    return value == "true"


async def set_search_index_dirty(
    state: AsyncSession,
    dirty: bool,
) -> None:
    value = "true" if dirty else "false"
    await state.execute(
        text(
            "INSERT INTO system_settings("
            "key, value, value_type, updated_at"
            ") VALUES ("
            ":key, :value, 'boolean', CURRENT_TIMESTAMP"
            ") ON CONFLICT(key) DO UPDATE SET "
            "value = excluded.value, "
            "value_type = excluded.value_type, "
            "updated_at = CURRENT_TIMESTAMP"
        ),
        {
            "key": SEARCH_INDEX_DIRTY_KEY,
            "value": value,
        },
    )
    await state.commit()


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
_CATALOG_PROJECTION_STATE_UPSERT_SQL = text(
    "INSERT INTO catalog_search_projection_state("
    "entry_id, applied_revision, updated_at"
    ") VALUES (:entry_id, :applied_revision, :updated_at) "
    "ON CONFLICT(entry_id) DO UPDATE SET "
    "applied_revision = :applied_revision, updated_at = :updated_at"
)
_CATALOG_PROJECTION_STATE_GET_SQL = text(
    "SELECT applied_revision FROM catalog_search_projection_state "
    "WHERE entry_id = :entry_id"
)


async def catalog_projection_revision(
    index: AsyncSession,
    *,
    entry_id: str,
) -> int | None:
    value = (
        await index.execute(
            _CATALOG_PROJECTION_STATE_GET_SQL,
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
    updated_at,
) -> None:
    await index.execute(
        _CATALOG_PROJECTION_STATE_UPSERT_SQL,
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
) -> list[dict[str, object]]:
    normalized = " ".join(query.strip().split())
    if not normalized:
        return []
    fts_query = build_fts_query(normalized)
    if not fts_query:
        return []

    sql = text(
        "SELECT entry_id, content_type, title FROM catalog_search_fts "
        "WHERE catalog_search_fts MATCH :fts_query"
        + (" AND content_type = :content_type" if content_type else "")
        + " LIMIT :limit"
    )
    params: dict[str, object] = {
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
    "SEARCH_INDEX_DIRTY_KEY",
    "search_candidates",
    "rebuild_search_index",
    "search_index_is_dirty",
    "set_search_index_dirty",
    "catalog_projection_revision",
    "catalog_search_fts_match",
    "clear_catalog_search_projection",
    "delete_catalog_search_document",
    "set_catalog_projection_revision",
    "upsert_catalog_search_document",
]
