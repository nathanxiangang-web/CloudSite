import re
from collections.abc import Iterable
from typing import Any

from sqlalchemy import bindparam, select, text

from .database import IndexSession, StateSession
from .models import Folder, Resource, SystemSetting


SEARCH_TYPES = {"software", "image", "video", "document", "file"}
SEARCH_OBJECT_TYPES = {"all", "resource", "folder"}
SEARCH_SORTS = {"relevance", "modified_at", "name", "size"}
SEARCH_INDEX_DIRTY_KEY = "search_index_dirty"


def normalize_search_query(value: str) -> str:
    return " ".join(value.strip().split())


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def build_fts_query(value: str) -> str:
    tokens = re.findall(r"[0-9A-Za-z\u0080-\uffff]+", value)[:8]
    return " AND ".join(f'"{token.replace(chr(34), chr(34) * 2)}"*' for token in tokens)


def classify_match(name: str, query: str) -> str:
    lowered_name = name.casefold()
    lowered_query = query.casefold()
    if lowered_name == lowered_query:
        return "exact"
    if lowered_name.startswith(lowered_query):
        return "prefix"
    if lowered_query in lowered_name:
        return "name"
    return "metadata"


async def rebuild_search_index(session, folders: Iterable[Any], resources: Iterable[Any]) -> int:
    await session.execute(text("DELETE FROM search_fts"))
    statement = text(
        "INSERT INTO search_fts(object_id, object_type, name, extension, content_type, description, tags, breadcrumb_text) "
        "VALUES (:id, :object_type, :name, :extension, :content_type, :description, :tags, :breadcrumb_text)"
    )
    rows: list[dict[str, str]] = []
    for row in folders:
        if getattr(row, "status", "active") != "active":
            continue
        rows.append({
            "id": row.id,
            "object_type": "folder",
            "name": row.name,
            "extension": "",
            "content_type": row.content_type,
            "description": "",
            "tags": "",
            "breadcrumb_text": row.path,
        })
    for row in resources:
        if getattr(row, "status", "active") != "active":
            continue
        rows.append({
            "id": row.id,
            "object_type": "resource",
            "name": row.name,
            "extension": getattr(row, "extension", "") or "",
            "content_type": row.content_type,
            "description": "",
            "tags": "",
            "breadcrumb_text": row.path,
        })
    if rows:
        await session.execute(statement, rows)
    return len(rows)


async def set_search_index_dirty(dirty: bool) -> None:
    async with StateSession() as session:
        row = await session.get(SystemSetting, SEARCH_INDEX_DIRTY_KEY)
        value = "true" if dirty else "false"
        if row is None:
            session.add(SystemSetting(key=SEARCH_INDEX_DIRTY_KEY, value=value, value_type="boolean"))
        else:
            row.value = value
            row.value_type = "boolean"
        await session.commit()


async def recover_search_index_if_dirty() -> int:
    async with StateSession() as state:
        row = await state.get(SystemSetting, SEARCH_INDEX_DIRTY_KEY)
        if row is None or row.value != "true":
            return 0
    async with IndexSession() as session:
        folders = list((await session.scalars(select(Folder).where(Folder.status == "active"))).all())
        resources = list((await session.scalars(select(Resource).where(Resource.status == "active"))).all())
        count = await rebuild_search_index(session, folders, resources)
        await session.commit()
    await set_search_index_dirty(False)
    return count


async def search_index(
    session,
    query: str,
    content_type: str | None,
    object_type: str,
    page: int,
    page_size: int,
    sort: str,
    enabled_root_ids: set[int] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    if enabled_root_ids is not None and not enabled_root_ids:
        return [], 0
    escaped = escape_like(query)
    parameters: dict[str, Any] = {
        "query": query,
        "query_lower": query.casefold(),
        "like": f"%{escaped}%",
        "prefix": f"{escaped}%",
        "content_type": content_type,
        "object_type": None if object_type == "all" else object_type,
        "limit": page_size,
        "offset": (page - 1) * page_size,
    }
    fts_query = build_fts_query(query)
    fts_clause = " OR rowid IN (SELECT rowid FROM search_fts WHERE search_fts MATCH :fts_query)" if fts_query else ""
    if fts_query:
        parameters["fts_query"] = fts_query

    if enabled_root_ids is not None:
        parameters["enabled_root_ids"] = list(enabled_root_ids)
        scope_r = " AND resources.root_mapping_id IN :enabled_root_ids"
        scope_f = " AND folders.root_mapping_id IN :enabled_root_ids"
    else:
        scope_r = scope_f = ""

    common = f"""
        WITH matched AS (
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
              AND (name LIKE :like ESCAPE '\\'
                   OR extension LIKE :like ESCAPE '\\'
                   OR description LIKE :like ESCAPE '\\'
                   OR tags LIKE :like ESCAPE '\\'
                   OR breadcrumb_text LIKE :like ESCAPE '\\'{fts_clause})
        ), candidates AS (
            SELECT matched.object_id, matched.object_type, matched.name, matched.extension,
                   matched.content_type, matched.relevance, resources.size,
                   resources.modified_at, resources.parent_id
            FROM matched JOIN resources ON matched.object_type = 'resource'
              AND resources.id = matched.object_id AND resources.status = 'active'{scope_r}
            UNION ALL
            SELECT matched.object_id, matched.object_type, matched.name, matched.extension,
                   matched.content_type, matched.relevance, NULL AS size,
                   folders.modified_at, folders.parent_id
            FROM matched JOIN folders ON matched.object_type = 'folder'
              AND folders.id = matched.object_id AND folders.status = 'active'{scope_f}
        )
    """
    order_by = {
        "relevance": "relevance DESC, name COLLATE NOCASE ASC, object_id ASC",
        "modified_at": "CASE WHEN modified_at IS NULL THEN 1 ELSE 0 END, modified_at DESC, name COLLATE NOCASE ASC",
        "name": "name COLLATE NOCASE ASC, object_id ASC",
        "size": "CASE WHEN size IS NULL THEN 1 ELSE 0 END, size DESC, name COLLATE NOCASE ASC",
    }[sort]
    def _bind(stmt):
        return stmt.bindparams(bindparam("enabled_root_ids", expanding=True)) if enabled_root_ids is not None else stmt

    total = int((await session.execute(_bind(text(common + " SELECT COUNT(*) FROM candidates")), parameters)).scalar_one())
    result = await session.execute(
        _bind(text(common + f" SELECT * FROM candidates ORDER BY {order_by} LIMIT :limit OFFSET :offset")),
        parameters,
    )
    return [dict(row) for row in result.mappings().all()], total
