"""resources 路由：资源列表、详情、文件夹。"""
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query
from ..modules.providers.contracts.public import provider_runtime
from ..modules.resources.api.queries import resource_queries
from ..modules.resources.domain.errors import (
    FolderNotFoundError,
    ResourceNotAvailableError,
    ResourceNotFoundError,
)
from ..office import OfficePreviewError, ensure_preview_cached, office_cache_filename, render_pdf_pages
from ..preview import PreviewError, create_preview_ticket, load_text_preview, preview_capability
from ..schemas import (
    FolderDetailOutput,
    FolderListOutput,
    ResourceDetailOutput,
    ResourcePageOutput,
    TextPreviewOutput,
)
from ..shares.service import enabled_root_ids

router = APIRouter()


async def _preview_resource(index, state, resource_id: str):
    enabled_ids = await enabled_root_ids(state)
    try:
        return await resource_queries(index).preview_resource(
            resource_id=resource_id,
            enabled_root_ids=enabled_ids,
        )
    except (ResourceNotFoundError, ResourceNotAvailableError) as exc:
        raise HTTPException(
            404,
            {"code": "PV-001", "message": "资源不存在或已不可用"},
        ) from exc


@router.get("/api/resources", response_model=ResourcePageOutput)
async def resources(
    resource_type: str | None = Query(None, alias="type"),
    content_type: str | None = None,
    folder_id: str | None = None,
    parent_id: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    sort: str = "modified_at",
    order: str = "desc",
):
    from ..main import IndexSession, StateSession

    selected_type = resource_type or content_type
    selected_folder = folder_id or parent_id
    if sort not in {"name", "modified_at", "modified", "size"} or order not in {"asc", "desc"}:
        raise HTTPException(400, {"code": "API-001", "message": "排序参数无效"})

    async with IndexSession() as session, StateSession() as state:
        enabled_ids = await enabled_root_ids(state)
        page_view = await resource_queries(session).list_resources(
            enabled_root_ids=enabled_ids,
            content_type=selected_type,
            parent_id=selected_folder,
            page=page,
            page_size=page_size,
            sort=sort,
            order=order,
        )
        return page_view.to_dict()


@router.get("/api/resources/{resource_id}", response_model=ResourceDetailOutput)
async def resource_detail(resource_id: str):
    from ..main import IndexSession, StateSession

    async with IndexSession() as session, StateSession() as state:
        enabled_ids = await enabled_root_ids(state)
        try:
            detail = await resource_queries(session).resource_detail(
                resource_id=resource_id,
                enabled_root_ids=enabled_ids,
            )
        except ResourceNotFoundError as exc:
            raise HTTPException(
                404,
                {"code": "RS-001", "message": "资源不存在或已不可用"},
            ) from exc
        except ResourceNotAvailableError as exc:
            raise HTTPException(
                404,
                {"code": "RESOURCE_NOT_AVAILABLE", "message": "资源不存在或已不可用"},
            ) from exc

        payload = detail.to_dict()
        payload["capabilities"] = preview_capability(detail.resource)
        return payload


@router.get("/api/resources/{resource_id}/preview")
async def resource_preview_capability(resource_id: str):
    from ..main import IndexSession, StateSession

    async with IndexSession() as session, StateSession() as state:
        resource = await _preview_resource(session, state, resource_id)
        return preview_capability(resource)


@router.get("/api/resources/{resource_id}/text-preview", response_model=TextPreviewOutput)
async def resource_text_preview(resource_id: str):
    from ..main import IndexSession, StateSession

    async with IndexSession() as index, StateSession() as state:
        resource = await _preview_resource(index, state, resource_id)
        runtime = provider_runtime(state)
        try:
            return await load_text_preview(resource, runtime)
        except PreviewError as exc:
            raise HTTPException(exc.status_code, {"code": exc.code, "message": exc.message}) from exc


@router.get("/api/resources/{resource_id}/pdf-preview")
async def resource_pdf_preview(resource_id: str):
    from ..main import IndexSession, StateSession

    async with IndexSession() as index, StateSession() as state:
        resource = await _preview_resource(index, state, resource_id)
        if preview_capability(resource)["preview_type"] != "pdf":
            raise HTTPException(400, {"code": "PV-002", "message": "该资源不支持 PDF 在线预览"})
        runtime = provider_runtime(state)
        try:
            await ensure_preview_cached(resource, runtime)
        except OfficePreviewError as exc:
            raise HTTPException(exc.status_code, {"code": exc.code, "message": exc.message}) from exc
        return {"url": f"/office-files/{office_cache_filename(resource)}?{urlencode({'ticket': create_preview_ticket(resource.id)})}"}


@router.get("/api/resources/{resource_id}/office-preview")
async def resource_office_preview(resource_id: str):
    from ..main import IndexSession, StateSession

    async with IndexSession() as index, StateSession() as state:
        resource = await _preview_resource(index, state, resource_id)
        if preview_capability(resource)["preview_type"] != "office":
            raise HTTPException(400, {"code": "PV-002", "message": "该资源不支持 Office 在线预览"})
        runtime = provider_runtime(state)
        try:
            await ensure_preview_cached(resource, runtime)
        except OfficePreviewError as exc:
            raise HTTPException(exc.status_code, {"code": exc.code, "message": exc.message}) from exc
        return {"url": f"/office-files/{office_cache_filename(resource)}?{urlencode({'ticket': create_preview_ticket(resource.id)})}"}


@router.get("/api/folders", response_model=FolderListOutput)
async def folders(content_type: str | None = None, parent_id: str | None = None):
    from ..main import IndexSession, StateSession

    async with IndexSession() as session, StateSession() as state:
        enabled_ids = await enabled_root_ids(state)
        items = await resource_queries(session).list_folders(
            enabled_root_ids=enabled_ids,
            content_type=content_type,
            parent_id=parent_id,
            parent_filter_supplied=parent_id is not None,
        )
        return {"items": [item.to_dict() for item in items]}


@router.get("/api/folders/{folder_id}", response_model=FolderDetailOutput)
async def folder_detail(
    folder_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    sort: str = "name",
    order: str = "asc",
):
    from ..main import IndexSession, StateSession

    if sort not in {"name", "modified_at", "size"} or order not in {"asc", "desc"}:
        raise HTTPException(400, {"code": "API-001", "message": "排序参数无效"})

    async with IndexSession() as session, StateSession() as state:
        enabled_ids = await enabled_root_ids(state)
        try:
            detail = await resource_queries(session).folder_detail(
                folder_id=folder_id,
                enabled_root_ids=enabled_ids,
                page=page,
                page_size=page_size,
                sort=sort,
                order=order,
            )
        except FolderNotFoundError as exc:
            raise HTTPException(
                404,
                {"code": "FD-001", "message": "文件夹不存在或已不可用"},
            ) from exc
        return detail.to_dict()

