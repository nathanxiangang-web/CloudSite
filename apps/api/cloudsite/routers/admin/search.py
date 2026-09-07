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