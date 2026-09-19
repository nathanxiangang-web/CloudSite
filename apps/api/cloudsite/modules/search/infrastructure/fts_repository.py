"""SQLite FTS persistence adapter owned by Search."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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


__all__ = [
    "SEARCH_INDEX_DIRTY_KEY",
    "search_candidates",
    "rebuild_search_index",
    "set_search_index_dirty",
]
