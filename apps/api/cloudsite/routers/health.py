"""health 路由：健康检查端点。"""
from fastapi import APIRouter

from .. import __version__

router = APIRouter()


@router.get("/api/health")
async def health():
    return {"status": "healthy", "version": __version__, "database": "SQLite 3"}
