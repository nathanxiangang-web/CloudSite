"""B2 公开站点地图：GET /sitemap.xml 只含 publicly_visible=True 的条目。"""
from fastapi import APIRouter, Response

from ..services.publication_scope import build_sitemap_xml, list_public_entries

router = APIRouter(tags=["sitemap"])


@router.get("/sitemap.xml")
async def sitemap():
    from ..main import StateSession

    base_url = "http://localhost"
    async with StateSession() as state:
        entries = await list_public_entries(state)
    xml = build_sitemap_xml(entries, base_url)
    return Response(content=xml, media_type="application/xml")
