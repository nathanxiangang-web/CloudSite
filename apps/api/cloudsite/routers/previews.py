"""previews 路由：302 预览跳转与 office 文件服务。"""
import logging
import time
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

from ..config import settings
from ..download import validate_resource_id
from ..models import Resource
from ..office import OFFICE_CONTENT_TYPES, office_content_type
from ..preview import PreviewError, resolve_preview_url
from ..services.connections import resolve_resource_connection
from ..shares.service import resource_in_publication_scope

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/office-files/{filename}")
async def serve_office_file(filename: str):
    from ..main import IndexSession, StateSession

    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, "无效的预览文件名")
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    if extension not in OFFICE_CONTENT_TYPES:
        raise HTTPException(403, {"code": "PV-002", "message": "该格式不支持在线预览"})
    resource_id = filename.rsplit(".", 1)[0] if "." in filename else filename
    async with IndexSession() as index, StateSession() as state:
        resource = await index.get(Resource, resource_id)
        if not resource or resource.status != "active" or not await resource_in_publication_scope(state, resource):
            raise HTTPException(404, {"code": "PV-001", "message": "资源不存在或已不可用"})
    path = settings.office_cache_dir / filename
    if not path.is_file():
        raise HTTPException(404, "预览文件不存在或已过期")
    return FileResponse(path, media_type=office_content_type(extension), content_disposition_type="inline")


def _preview_error_redirect(resource_id: str, code: str) -> RedirectResponse:
    return RedirectResponse(f"/resource/{resource_id}?{urlencode({'preview_error': code})}", status_code=302)


@router.get("/p/{resource_id}")
async def preview(resource_id: str, refresh: bool = False):
    from ..main import IndexSession, StateSession

    started = time.perf_counter()
    if not validate_resource_id(resource_id):
        return _preview_error_redirect(resource_id[:64], "PV-001")
    async with IndexSession() as index, StateSession() as state:
        resource = await index.get(Resource, resource_id)
        if not resource or resource.status != "active":
            return _preview_error_redirect(resource_id, "PV-001")
        if not await resource_in_publication_scope(state, resource):
            return _preview_error_redirect(resource_id, "PV-001")
        connection = await resolve_resource_connection(state, resource)
        try:
            resolve_started = time.perf_counter()
            resolution = await resolve_preview_url(resource, connection, force_refresh=refresh)
            resolve_ms = (time.perf_counter() - resolve_started) * 1000
            redirect_ms = (time.perf_counter() - started) * 1000
            logger.debug(
                "preview metrics resource_id=%s preview_resolve_ms=%.2f preview_redirect_ms=%.2f cache_hit=%s",
                resource_id,
                resolve_ms,
                redirect_ms,
                getattr(resolution, "cache_hit", False),
            )
            return RedirectResponse(resolution.url, status_code=302)
        except PreviewError as exc:
            return _preview_error_redirect(resource.id, exc.code)
