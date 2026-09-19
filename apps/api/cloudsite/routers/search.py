"""search routes."""

from fastapi import APIRouter, HTTPException, Query

from ..indexer import log_operation
from ..modules.providers.contracts.public import enabled_root_ids
from ..modules.search.contracts.public import (
    SEARCH_OBJECT_TYPES,
    SEARCH_SORTS,
    SEARCH_TYPES,
    normalize_search_query,
    search_public_resources,
)
from ..schemas import SearchOutput

router = APIRouter()


@router.get("/api/search", response_model=SearchOutput)
async def search(
    q: str = "",
    resource_type: str | None = Query(default=None, alias="type"),
    object_type: str = "all",
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    sort: str = "relevance",
):
    from ..main import IndexSession, StateSession

    normalized = normalize_search_query(q)
    if not normalized:
        raise HTTPException(
            400,
            {"code": "SRCH-001", "message": "搜索关键词为空"},
        )
    if len(normalized) > 200:
        raise HTTPException(
            400,
            {"code": "SRCH-002", "message": "搜索关键词过长"},
        )
    if (
        resource_type is not None
        and resource_type not in SEARCH_TYPES
    ):
        raise HTTPException(
            400,
            {"code": "SRCH-004", "message": "资源类型无效"},
        )
    if (
        object_type not in SEARCH_OBJECT_TYPES
        or sort not in SEARCH_SORTS
    ):
        raise HTTPException(
            400,
            {"code": "SRCH-004", "message": "搜索参数无效"},
        )

    try:
        async with IndexSession() as index, StateSession() as state:
            root_ids = await enabled_root_ids(state)
            result = await search_public_resources(
                index,
                query=normalized,
                resource_type=resource_type,
                object_type=object_type,
                page=page,
                page_size=page_size,
                sort=sort,
                enabled_root_ids=root_ids,
            )
            from ..services.metrics import (
                EVENT_SEARCH_PERFORMED,
                try_record_committed,
            )

            await try_record_committed(
                state,
                EVENT_SEARCH_PERFORMED,
                {
                    "result_count": result["total"],
                    "raw_query": normalized,
                },
            )
            return result
    except HTTPException:
        raise
    except Exception as exc:
        await log_operation(
            "search",
            "query_failed",
            type(exc).__name__,
            level="ERROR",
        )
        raise HTTPException(
            503,
            {
                "code": "SRCH-003",
                "message": "搜索索引暂时不可用",
            },
        ) from exc
