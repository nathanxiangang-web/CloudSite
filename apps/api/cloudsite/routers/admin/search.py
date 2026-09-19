"""admin/search routes."""

from fastapi import APIRouter

from ...indexer import log_operation
from ...modules.search.contracts.public import (
    rebuild_public_search_index as run_public_search_rebuild,
)

router = APIRouter()


@router.post("/api/admin/search/rebuild")
async def rebuild_public_search_index():
    from ...main import IndexSession, StateSession

    async with StateSession() as state, IndexSession() as index:
        result = await run_public_search_rebuild(state, index)
    await log_operation(
        "search",
        "rebuild",
        f"搜索索引重建完成：{result.indexed} 个对象",
    )
    return {
        "ok": True,
        "indexed": result.indexed,
        "folders": result.folders,
        "resources": result.resources,
    }


@router.post("/api/admin/catalog/search/rebuild")
async def rebuild_catalog_search_projection():
    """全量重建 catalog 资源级检索投影（D1）。"""

    from ...main import IndexSession, StateSession
    from ...services.catalog_search_projection import (
        rebuild_catalog_search_index,
    )

    async with StateSession() as state, IndexSession() as index:
        count = await rebuild_catalog_search_index(state, index)
    await log_operation(
        "search",
        "catalog_rebuild",
        f"catalog 搜索投影重建完成：{count} 个条目",
    )
    return {"ok": True, "indexed": count}
