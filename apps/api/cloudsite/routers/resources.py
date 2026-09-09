"""resources 路由：资源列表、详情、文件夹。"""
import math

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import and_, desc, func, or_, select

from ..models import AListConnection, Folder, Resource
from ..office import OfficePreviewError, ensure_preview_cached, office_cache_filename
from ..preview import PreviewError, load_text_preview, preview_capability
from ..schemas import (
    FolderDetailOutput,
    FolderListOutput,
    ResourceDetailOutput,
    ResourcePageOutput,
    TextPreviewOutput,
)
from ..services.resources import (
    breadcrumbs_for_folder,
    folder_dict,
    resource_dict,
)
from ..shares.service import enabled_root_ids, resource_in_publication_scope

router = APIRouter()


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
    sort_columns = {"name": Resource.name, "modified_at": Resource.modified_at, "modified": Resource.modified_at, "size": Resource.size}
    if sort not in sort_columns or order not in {"asc", "desc"}:
        raise HTTPException(400, {"code": "API-001", "message": "排序参数无效"})
    async with IndexSession() as session, StateSession() as state:
        enabled_ids = await enabled_root_ids(state)
        scope_filter = Resource.root_mapping_id.in_(enabled_ids) if enabled_ids else False
        query = select(Resource).where(Resource.status == "active", scope_filter)
        count_query = select(func.count()).select_from(Resource).where(Resource.status == "active", scope_filter)
        if selected_type:
            query = query.where(Resource.content_type == selected_type)
            count_query = count_query.where(Resource.content_type == selected_type)
        if selected_folder:
            query = query.where(Resource.parent_id == selected_folder)
            count_query = count_query.where(Resource.parent_id == selected_folder)
        order_by = sort_columns[sort].asc() if order == "asc" else sort_columns[sort].desc()
        total = int(await session.scalar(count_query) or 0)
        rows = list((await session.scalars(query.order_by(order_by, Resource.id).offset((page - 1) * page_size).limit(page_size))).all())
        parent_ids = {row.parent_id for row in rows if row.parent_id}
        parents = {row.id: row for row in (await session.scalars(select(Folder).where(Folder.id.in_(parent_ids), Folder.status == "active"))).all()} if parent_ids else {}
        return {"items": [resource_dict(row, parents.get(row.parent_id or "")) for row in rows], "total": total, "page": page, "page_size": page_size, "total_pages": math.ceil(total / page_size) if total else 0}


@router.get("/api/resources/{resource_id}", response_model=ResourceDetailOutput)
async def resource_detail(resource_id: str):
    from ..main import IndexSession, StateSession

    async with IndexSession() as session, StateSession() as state:
        row = await session.get(Resource, resource_id)
        if not row or row.status != "active":
            raise HTTPException(404, {"code": "RS-001", "message": "资源不存在或已不可用"})
        if not await resource_in_publication_scope(state, row):
            raise HTTPException(404, {"code": "RESOURCE_NOT_AVAILABLE", "message": "资源不存在或已不可用"})
        parent = await session.get(Folder, row.parent_id) if row.parent_id else None
        breadcrumbs = await breadcrumbs_for_folder(session, parent)
        enabled_ids = await enabled_root_ids(state)
        sibling_scope = (
            Resource.status == "active",
            Resource.parent_id == row.parent_id,
            Resource.root_mapping_id == row.root_mapping_id,
            Resource.root_mapping_id.in_(enabled_ids) if enabled_ids else False,
        )
        related = list((await session.scalars(select(Resource).where(*sibling_scope, Resource.id != row.id).order_by(desc(Resource.modified_at)).limit(8))).all())
        # 只查相邻的 prev/next（各 limit 1），不加载全部 siblings
        previous = (await session.scalars(select(Resource).where(
            *sibling_scope, Resource.content_type == row.content_type,
            or_(Resource.name < row.name, and_(Resource.name == row.name, Resource.id < row.id)),
        ).order_by(desc(Resource.name), desc(Resource.id)).limit(1))).first()
        next_item = (await session.scalars(select(Resource).where(
            *sibling_scope, Resource.content_type == row.content_type,
            or_(Resource.name > row.name, and_(Resource.name == row.name, Resource.id > row.id)),
        ).order_by(Resource.name, Resource.id).limit(1))).first()
        return {
            **resource_dict(row, parent),
            "breadcrumbs": breadcrumbs,
            "related": [resource_dict(item, parent) for item in related],
            "capabilities": preview_capability(row),
            "previous": resource_dict(previous, parent) if previous else None,
            "next": resource_dict(next_item, parent) if next_item else None,
        }


@router.get("/api/resources/{resource_id}/preview")
async def resource_preview_capability(resource_id: str):
    from ..main import IndexSession, StateSession

    async with IndexSession() as session, StateSession() as state:
        resource = await session.get(Resource, resource_id)
        if not resource or resource.status != "active" or not await resource_in_publication_scope(state, resource):
            raise HTTPException(404, {"code": "PV-001", "message": "资源不存在或已不可用"})
        return preview_capability(resource)


@router.get("/api/resources/{resource_id}/text-preview", response_model=TextPreviewOutput)
async def resource_text_preview(resource_id: str):
    from ..main import IndexSession, StateSession

    async with IndexSession() as index, StateSession() as state:
        resource = await index.get(Resource, resource_id)
        if not resource or resource.status != "active" or not await resource_in_publication_scope(state, resource):
            raise HTTPException(404, {"code": "PV-001", "message": "资源不存在或已不可用"})
        connection = await state.get(AListConnection, 1)
        try:
            return await load_text_preview(resource, connection)
        except PreviewError as exc:
            raise HTTPException(exc.status_code, {"code": exc.code, "message": exc.message}) from exc


@router.get("/api/resources/{resource_id}/pdf-preview")
async def resource_pdf_preview(resource_id: str):
    from ..main import IndexSession, StateSession

    async with IndexSession() as index, StateSession() as state:
        resource = await index.get(Resource, resource_id)
        if not resource or resource.status != "active" or not await resource_in_publication_scope(state, resource):
            raise HTTPException(404, {"code": "PV-001", "message": "资源不存在或已不可用"})
        if preview_capability(resource)["preview_type"] != "pdf":
            raise HTTPException(400, {"code": "PV-002", "message": "该资源不支持 PDF 在线预览"})
        connection = await state.get(AListConnection, 1)
        try:
            await ensure_preview_cached(resource, connection)
        except OfficePreviewError as exc:
            raise HTTPException(exc.status_code, {"code": exc.code, "message": exc.message}) from exc
        return {"url": f"/office-files/{office_cache_filename(resource)}"}


@router.get("/api/resources/{resource_id}/office-preview")
async def resource_office_preview(resource_id: str):
    from ..main import IndexSession, StateSession

    async with IndexSession() as index, StateSession() as state:
        resource = await index.get(Resource, resource_id)
        if not resource or resource.status != "active" or not await resource_in_publication_scope(state, resource):
            raise HTTPException(404, {"code": "PV-001", "message": "资源不存在或已不可用"})
        if preview_capability(resource)["preview_type"] != "office":
            raise HTTPException(400, {"code": "PV-002", "message": "该资源不支持 Office 在线预览"})
        connection = await state.get(AListConnection, 1)
        try:
            await ensure_preview_cached(resource, connection)
        except OfficePreviewError as exc:
            raise HTTPException(exc.status_code, {"code": exc.code, "message": exc.message}) from exc
        return {"url": f"/office-files/{office_cache_filename(resource)}"}


@router.get("/api/folders", response_model=FolderListOutput)
async def folders(content_type: str | None = None, parent_id: str | None = None):
    from ..main import IndexSession, StateSession

    async with IndexSession() as session, StateSession() as state:
        enabled_ids = await enabled_root_ids(state)
        if not enabled_ids:
            return {"items": []}
        query = select(Folder).where(Folder.status == "active", Folder.root_mapping_id.in_(enabled_ids))
        if content_type:
            query = query.where(Folder.content_type == content_type)
        if parent_id is not None:
            query = query.where(Folder.parent_id == (parent_id or None))
        rows = list((await session.scalars(query.order_by(Folder.depth, Folder.name))).all())
        return {"items": [folder_dict(row) for row in rows]}


@router.get("/api/folders/{folder_id}", response_model=FolderDetailOutput)
async def folder_detail(
    folder_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    sort: str = "name",
    order: str = "asc",
):
    from ..main import IndexSession, StateSession

    sort_columns = {"name": Resource.name, "modified_at": Resource.modified_at, "size": Resource.size}
    if sort not in sort_columns or order not in {"asc", "desc"}:
        raise HTTPException(400, {"code": "API-001", "message": "排序参数无效"})
    async with IndexSession() as session, StateSession() as state:
        enabled_ids = await enabled_root_ids(state)
        row = await session.get(Folder, folder_id)
        if not row or row.status != "active" or row.root_mapping_id not in enabled_ids:
            raise HTTPException(404, {"code": "FD-001", "message": "文件夹不存在或已不可用"})
        breadcrumbs = await breadcrumbs_for_folder(session, row)
        child_folders = list((await session.scalars(select(Folder).where(Folder.parent_id == folder_id, Folder.status == "active", Folder.root_mapping_id.in_(enabled_ids)).order_by(Folder.name))).all())
        resource_query = select(Resource).where(Resource.parent_id == folder_id, Resource.status == "active", Resource.root_mapping_id.in_(enabled_ids))
        total = int(await session.scalar(select(func.count()).select_from(Resource).where(Resource.parent_id == folder_id, Resource.status == "active", Resource.root_mapping_id.in_(enabled_ids))) or 0)
        order_by = sort_columns[sort].asc() if order == "asc" else sort_columns[sort].desc()
        child_resources = list((await session.scalars(resource_query.order_by(order_by, Resource.id).offset((page - 1) * page_size).limit(page_size))).all())
        return {
            "folder": folder_dict(row),
            "breadcrumbs": breadcrumbs,
            "child_folders": [folder_dict(item) for item in child_folders],
            "resources": {"items": [resource_dict(item, row) for item in child_resources], "page": page, "page_size": page_size, "total": total, "total_pages": math.ceil(total / page_size) if total else 0},
        }
