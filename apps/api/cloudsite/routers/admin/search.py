"""admin/search 路由：搜索索引重建。"""
from fastapi import APIRouter
from sqlalchemy import select

from ...indexer import log_operation
from ...models import Folder, Resource
from ...search import rebuild_search_index, set_search_index_dirty

router = APIRouter()


@router.post("/api/admin/search/rebuild")
async def rebuild_public_search_index():
    from ...main import IndexSession

    await set_search_index_dirty(True)
    async with IndexSession() as session:
        folders = list((await session.scalars(select(Folder).where(Folder.status == "active"))).all())
        resources = list((await session.scalars(select(Resource).where(Resource.status == "active"))).all())
        count = await rebuild_search_index(session, folders, resources)
        await session.commit()
    await set_search_index_dirty(False)
    await log_operation("search", "rebuild", f"搜索索引重建完成：{count} 个对象")
    return {"ok": True, "indexed": count, "folders": len(folders), "resources": len(resources)}


@router.post("/api/admin/catalog/search/rebuild")
async def rebuild_catalog_search_projection():
    """全量重建 catalog 资源级检索投影（D1）。

    清空 catalog_search_fts 与水位表，为所有 published entry 重放 outbox 投影。
    重建后人工条目元数据仍可搜。不影响旧 search_fts 与 /api/search 契约。
    """
    from ...main import IndexSession, StateSession
    from ...services.catalog_search_projection import rebuild_catalog_search_index

    async with StateSession() as state, IndexSession() as index:
        count = await rebuild_catalog_search_index(state, index)
    await log_operation("search", "catalog_rebuild", f"catalog 搜索投影重建完成：{count} 个条目")
    return {"ok": True, "indexed": count}
