import asyncio
import base64
import hashlib
import hmac
import json
import math
import random
import secrets
import time
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from sqlalchemy import delete, desc, func, select, text

from . import __version__
from .alist import AListClient, AListError
from .config import settings
from .crypto import decrypt_secret, encrypt_secret
from .database import IndexSession, StateSession, init_databases
from .download import DownloadError, resolve_download_entry, validate_download_url, validate_resource_id
from .indexer import (
    automatic_sync_due,
    log_operation,
    normalize_path,
    recover_interrupted_sync_runs,
    run_sync,
    sync_circuit_status,
    sync_preflight,
)
from .models import (
    AListConnection,
    Collection,
    CollectionItem,
    ContentRootMapping,
    DownloadEvent,
    DownloadDiagnostic,
    Folder,
    OperationLog,
    Resource,
    Share,
    SiteSettings,
    SyncRun,
    SystemSetting,
    utcnow,
)
from .office import OfficePreviewError, ensure_preview_cached, office_cache_filename, office_content_type
from .preview import PreviewError, load_text_preview, preview_capability, resolve_preview_url
from .schemas import (
    AListInput,
    AdminLoginInput,
    ContentRootListOutput,
    CollectionInput,
    CollectionItemsInput,
    DownloadDiagnosticInput,
    RootMappingInput,
    FolderDetailOutput,
    FolderListOutput,
    ResourceDetailOutput,
    ResourcePageOutput,
    SearchOutput,
    ShareInput,
    ShareUpdate,
    SiteInput,
    SyncInput,
    SystemInput,
    TextPreviewOutput,
)
from .search import SEARCH_OBJECT_TYPES, SEARCH_SORTS, SEARCH_TYPES, classify_match, normalize_search_query, rebuild_search_index, search_index


scheduler_task: asyncio.Task | None = None
manual_sync_task: asyncio.Task | None = None
SESSION_COOKIE = "cloudsite_session"
_storage_info_cache: dict = {"data": None, "fetched_at": 0.0}
STORAGE_INFO_TTL_SECONDS = 600
SYNC_INTERVAL_OPTIONS = {180, 360, 720, 1440}


def create_session_token(username: str) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"username": username, "expires": int(time.time()) + 86400 * 7}, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def verify_session_token(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    payload, signature = token.rsplit(".", 1)
    expected = hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return False
    try:
        decoded = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return int(decoded.get("expires", 0)) > int(time.time())
    except Exception:
        return False


def alist_http_exception(exc: Exception, fallback_status: int = 502) -> HTTPException:
    if isinstance(exc, AListError):
        return HTTPException(exc.status_code, {"code": exc.code, "message": str(exc)})
    if isinstance(exc, ValueError):
        return HTTPException(400, {"code": "AL-006", "message": str(exc)})
    return HTTPException(fallback_status, {"code": "AL-999", "message": "AList 操作失败，请稍后重试"})


async def get_system_values(session) -> dict:
    rows = list((await session.scalars(select(SystemSetting))).all())
    values = {row.key: row.value for row in rows}
    interval = int(values.get("sync_interval_minutes", "360"))
    return {
        "automatic_sync": values.get("automatic_sync", "false") == "true",
        "sync_interval_minutes": interval if interval in SYNC_INTERVAL_OPTIONS else 360,
        "sync_on_startup": values.get("sync_on_startup", "false") == "true",
    }


async def scheduler_loop() -> None:
    while True:
        await asyncio.sleep(60)
        async with StateSession() as session:
            values = await get_system_values(session)
        if values["automatic_sync"] and await automatic_sync_due(values["sync_interval_minutes"]):
            with suppress(Exception):
                await run_sync("scheduled")


async def _run_manual_sync_in_background(full: bool, force: bool) -> None:
    global manual_sync_task
    try:
        await run_sync("manual", full, force)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        await log_operation("sync", "failed", f"后台同步启动失败：{str(exc)[:1000]}", level="ERROR")
    finally:
        manual_sync_task = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global scheduler_task, manual_sync_task
    await init_databases()
    await recover_interrupted_sync_runs()
    async with StateSession() as session:
        if not await session.get(SiteSettings, 1):
            session.add(SiteSettings(id=1))
        await session.commit()
        values = await get_system_values(session)
    scheduler_task = asyncio.create_task(scheduler_loop())
    if values["sync_on_startup"]:
        asyncio.create_task(_safe_startup_sync())
    yield
    if scheduler_task:
        scheduler_task.cancel()
        with suppress(asyncio.CancelledError):
            await scheduler_task
    if manual_sync_task and not manual_sync_task.done():
        manual_sync_task.cancel()
        with suppress(asyncio.CancelledError):
            await manual_sync_task


async def _safe_startup_sync():
    delay = random.uniform(
        settings.sync_startup_delay_min_seconds,
        settings.sync_startup_delay_max_seconds,
    )
    await asyncio.sleep(delay)
    async with StateSession() as session:
        values = await get_system_values(session)
    if not values["sync_on_startup"] or not await automatic_sync_due(values["sync_interval_minutes"]):
        return
    with suppress(Exception):
        await run_sync("startup")


app = FastAPI(title="CloudSite API", version=__version__, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def admin_session_middleware(request: Request, call_next):
    path = request.url.path
    if not path.startswith("/api/admin") or path.startswith("/api/admin/auth/"):
        return await call_next(request)
    async with StateSession() as session:
        connection = await session.get(AListConnection, 1)
    if not connection or not connection.enabled:
        return await call_next(request)
    if verify_session_token(request.cookies.get(SESSION_COOKIE)):
        return await call_next(request)
    return JSONResponse({"detail": "请先登录管理后台"}, status_code=401)


@app.get("/api/health")
async def health():
    return {"status": "healthy", "version": __version__, "database": "SQLite 3"}


@app.get("/api/admin/auth/status")
async def admin_auth_status(request: Request):
    async with StateSession() as session:
        connection = await session.get(AListConnection, 1)
    auth_required = bool(connection and connection.enabled)
    return {"auth_required": auth_required, "authenticated": not auth_required or verify_session_token(request.cookies.get(SESSION_COOKIE))}


@app.post("/api/admin/auth/login")
async def admin_login(payload: AdminLoginInput, response: Response):
    async with StateSession() as session:
        connection = await session.get(AListConnection, 1)
    if not connection or not connection.enabled:
        raise HTTPException(409, "请先在系统页配置 AList")
    try:
        await AListClient(connection.base_url, payload.username, payload.password).test()
    except Exception as exc:
        raise HTTPException(401, "账号或密码错误") from exc
    response.set_cookie(SESSION_COOKIE, create_session_token(payload.username), max_age=86400 * 7, httponly=True, samesite="lax", secure=False, path="/")
    return {"ok": True}


@app.post("/api/admin/auth/logout")
async def admin_logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


def resource_dict(row: Resource, parent: Folder | None = None) -> dict:
    payload = {
        "id": row.id,
        "name": row.name,
        "parent_id": row.parent_id,
        "content_type": row.content_type,
        "extension": row.extension,
        "mime_type": row.mime_type,
        "size": row.size,
        "modified_at": row.modified_at,
        "thumbnail": "",
    }
    if parent:
        payload["parent"] = {"id": parent.id, "name": parent.name}
    return payload


def folder_dict(row: Folder, include_path: bool = False) -> dict:
    payload = {
        "id": row.id,
        "name": row.name,
        "parent_id": row.parent_id,
        "content_type": row.content_type,
        "depth": row.depth,
        "child_folder_count": row.child_folder_count,
        "resource_count": row.resource_count,
        "modified_at": row.modified_at,
    }
    if include_path:
        payload["path"] = row.path
        payload["root_mapping_id"] = row.root_mapping_id
        payload["status"] = row.status
        payload["indexed_at"] = row.indexed_at
    return payload


def breadcrumbs_for(folder: Folder | None, folders_by_id: dict[str, Folder]) -> list[dict]:
    items: list[dict] = []
    current = folder
    visited: set[str] = set()
    while current and current.id not in visited:
        visited.add(current.id)
        items.append({"id": current.id, "name": current.name})
        current = folders_by_id.get(current.parent_id or "")
    return list(reversed(items))


async def collection_dict(state, index, row: Collection, include_items: bool = False) -> dict:
    items = list((await state.scalars(select(CollectionItem).where(CollectionItem.collection_id == row.id).order_by(CollectionItem.sort_order, CollectionItem.id))).all())
    payload = {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "cover": row.cover,
        "status": row.status,
        "visible_on_home": row.visible_on_home,
        "sort_order": row.sort_order,
        "item_count": len(items),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
    if include_items:
        resource_ids = [item.resource_id for item in items]
        resources_by_id = {}
        if resource_ids:
            resources_by_id = {resource.id: resource for resource in (await index.scalars(select(Resource).where(Resource.id.in_(resource_ids), Resource.status == "active"))).all()}
        payload["items"] = [resource_dict(resources_by_id[item.resource_id]) for item in items if item.resource_id in resources_by_id]
    return payload


def share_dict(row: Share) -> dict:
    return {
        "token": row.token,
        "object_type": row.object_type,
        "object_id": row.object_id,
        "title": row.title,
        "enabled": row.enabled,
        "expires_at": row.expires_at,
        "access_count": row.access_count,
        "last_accessed_at": row.last_accessed_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def share_is_expired(row: Share) -> bool:
    if not row.expires_at:
        return False
    expires_at = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= datetime.now(timezone.utc)


@app.get("/api/home")
async def home():
    async with StateSession() as state, IndexSession() as index:
        site = await state.get(SiteSettings, 1)
        root_rows = list((await state.scalars(select(ContentRootMapping).where(ContentRootMapping.enabled.is_(True)).order_by(ContentRootMapping.sort_order, ContentRootMapping.id))).all())
        counts = {}
        for content_type in ("software", "image", "video", "document", "file"):
            counts[content_type] = int(await index.scalar(select(func.count()).select_from(Resource).where(Resource.content_type == content_type, Resource.status == "active")) or 0)
        recent = list((await index.scalars(select(Resource).where(Resource.status == "active").order_by(desc(Resource.modified_at)).limit(site.recent_limit if site else 6))).all())
        popular = list((await index.scalars(select(Resource).where(Resource.status == "active").order_by(desc(Resource.size), desc(Resource.modified_at)).limit(site.popular_limit if site else 6))).all())
        collections = list((await state.scalars(select(Collection).where(Collection.visible_on_home.is_(True), Collection.status == "active").order_by(Collection.sort_order, desc(Collection.updated_at)).limit(site.collection_limit if site else 4))).all())
        content_roots = []
        for root in root_rows:
            content_roots.append({
                "id": root.id,
                "content_type": root.content_type,
                "display_name": root.display_name,
                "resource_count": int(await index.scalar(select(func.count()).select_from(Resource).where(Resource.root_mapping_id == root.id, Resource.status == "active")) or 0),
                "folder_count": int(await index.scalar(select(func.count()).select_from(Folder).where(Folder.root_mapping_id == root.id, Folder.status == "active")) or 0),
                "sort_order": root.sort_order,
            })
        resource_count = int(await index.scalar(select(func.count()).select_from(Resource).where(Resource.status == "active")) or 0)
        folder_count = int(await index.scalar(select(func.count()).select_from(Folder).where(Folder.status == "active")) or 0)
        total_size = int(await index.scalar(select(func.coalesce(func.sum(Resource.size), 0)).where(Resource.status == "active")) or 0)
        return {
            "site": {"site_name": site.site_name, "home_title": site.home_title, "description": site.description},
            "content_roots": content_roots,
            "stats": {"resource_count": resource_count, "folder_count": folder_count, "total_size": total_size},
            "recent_resources": [resource_dict(row) for row in recent],
            "counts": counts,
            "recent": [resource_dict(row) for row in recent],
            "popular": [resource_dict(row) for row in popular],
            "collections": [await collection_dict(state, index, row) for row in collections],
        }


@app.get("/api/storage/info")
async def storage_info():
    now = time.time()
    if _storage_info_cache["data"] is not None and (now - _storage_info_cache["fetched_at"]) < STORAGE_INFO_TTL_SECONDS:
        return _storage_info_cache["data"]
    async with StateSession() as session:
        connection = await session.get(AListConnection, 1)
    if not connection or not connection.enabled:
        info = {"primary": "网盘", "drives": []}
    else:
        try:
            password = decrypt_secret(connection.password_ciphertext)
            async with AListClient(connection.base_url, connection.username, password) as client:
                info = await client.get_storage_info(connection.base_path or "")
        except Exception:
            info = {"primary": "网盘", "drives": []}
    _storage_info_cache["data"] = info
    _storage_info_cache["fetched_at"] = now
    return info


@app.get("/api/content-roots", response_model=ContentRootListOutput)
async def public_content_roots():
    async with StateSession() as state, IndexSession() as index:
        roots = list((await state.scalars(select(ContentRootMapping).where(ContentRootMapping.enabled.is_(True)).order_by(ContentRootMapping.sort_order, ContentRootMapping.id))).all())
        items = []
        for root in roots:
            items.append({
                "id": root.id,
                "content_type": root.content_type,
                "display_name": root.display_name,
                "resource_count": int(await index.scalar(select(func.count()).select_from(Resource).where(Resource.root_mapping_id == root.id, Resource.status == "active")) or 0),
                "folder_count": int(await index.scalar(select(func.count()).select_from(Folder).where(Folder.root_mapping_id == root.id, Folder.status == "active")) or 0),
                "sort_order": root.sort_order,
            })
        return {"items": items}


@app.get("/api/resources", response_model=ResourcePageOutput)
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
    selected_type = resource_type or content_type
    selected_folder = folder_id or parent_id
    sort_columns = {"name": Resource.name, "modified_at": Resource.modified_at, "modified": Resource.modified_at, "size": Resource.size}
    if sort not in sort_columns or order not in {"asc", "desc"}:
        raise HTTPException(400, {"code": "API-001", "message": "排序参数无效"})
    async with IndexSession() as session:
        query = select(Resource).where(Resource.status == "active")
        count_query = select(func.count()).select_from(Resource).where(Resource.status == "active")
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


@app.get("/api/resources/{resource_id}", response_model=ResourceDetailOutput)
async def resource_detail(resource_id: str):
    async with IndexSession() as session:
        row = await session.get(Resource, resource_id)
        if not row or row.status != "active":
            raise HTTPException(404, {"code": "RS-001", "message": "资源不存在或已不可用"})
        parent = await session.get(Folder, row.parent_id) if row.parent_id else None
        all_folders = {item.id: item for item in (await session.scalars(select(Folder).where(Folder.status == "active"))).all()}
        related = list((await session.scalars(select(Resource).where(Resource.status == "active", Resource.parent_id == row.parent_id, Resource.id != row.id).order_by(desc(Resource.modified_at)).limit(8))).all())
        siblings = list((await session.scalars(select(Resource).where(Resource.status == "active", Resource.parent_id == row.parent_id, Resource.content_type == row.content_type).order_by(Resource.name, Resource.id))).all())
        sibling_index = next((index for index, item in enumerate(siblings) if item.id == row.id), -1)
        previous = siblings[sibling_index - 1] if sibling_index > 0 else None
        next_item = siblings[sibling_index + 1] if sibling_index >= 0 and sibling_index + 1 < len(siblings) else None
        return {
            **resource_dict(row, parent),
            "breadcrumbs": breadcrumbs_for(parent, all_folders),
            "related": [resource_dict(item, parent) for item in related],
            "capabilities": preview_capability(row),
            "previous": resource_dict(previous, parent) if previous else None,
            "next": resource_dict(next_item, parent) if next_item else None,
        }


@app.get("/api/resources/{resource_id}/preview")
async def resource_preview_capability(resource_id: str):
    async with IndexSession() as session:
        resource = await session.get(Resource, resource_id)
        if not resource or resource.status != "active":
            raise HTTPException(404, {"code": "PV-001", "message": "资源不存在或已不可用"})
        return preview_capability(resource)


@app.get("/api/resources/{resource_id}/text-preview", response_model=TextPreviewOutput)
async def resource_text_preview(resource_id: str):
    async with IndexSession() as index, StateSession() as state:
        resource = await index.get(Resource, resource_id)
        if not resource or resource.status != "active":
            raise HTTPException(404, {"code": "PV-001", "message": "资源不存在或已不可用"})
        connection = await state.get(AListConnection, 1)
        try:
            return await load_text_preview(resource, connection)
        except PreviewError as exc:
            raise HTTPException(exc.status_code, {"code": exc.code, "message": exc.message}) from exc


@app.get("/api/resources/{resource_id}/office-preview")
async def resource_office_preview(resource_id: str):
    async with IndexSession() as index, StateSession() as state:
        resource = await index.get(Resource, resource_id)
        if not resource or resource.status != "active":
            raise HTTPException(404, {"code": "PV-001", "message": "资源不存在或已不可用"})
        if preview_capability(resource)["preview_type"] != "office":
            raise HTTPException(400, {"code": "PV-002", "message": "该资源不支持 Office 在线预览"})
        connection = await state.get(AListConnection, 1)
        try:
            await ensure_preview_cached(resource, connection)
        except OfficePreviewError as exc:
            raise HTTPException(exc.status_code, {"code": exc.code, "message": exc.message}) from exc
        return {"url": f"/office-files/{office_cache_filename(resource)}"}


@app.get("/api/resources/{resource_id}/pdf-preview")
async def resource_pdf_preview(resource_id: str):
    async with IndexSession() as index, StateSession() as state:
        resource = await index.get(Resource, resource_id)
        if not resource or resource.status != "active":
            raise HTTPException(404, {"code": "PV-001", "message": "资源不存在或已不可用"})
        if preview_capability(resource)["preview_type"] != "pdf":
            raise HTTPException(400, {"code": "PV-002", "message": "该资源不支持 PDF 在线预览"})
        connection = await state.get(AListConnection, 1)
        try:
            await ensure_preview_cached(resource, connection)
        except OfficePreviewError as exc:
            raise HTTPException(exc.status_code, {"code": exc.code, "message": exc.message}) from exc
        return {"url": f"/office-files/{office_cache_filename(resource)}"}


@app.get("/office-files/{filename}")
async def serve_office_file(filename: str):
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, "无效的预览文件名")
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    path = settings.office_cache_dir / filename
    if not path.is_file():
        raise HTTPException(404, "预览文件不存在或已过期")
    return FileResponse(path, media_type=office_content_type(extension), filename=filename, content_disposition_type="inline")


@app.get("/api/folders", response_model=FolderListOutput)
async def folders(content_type: str | None = None, parent_id: str | None = None):
    async with IndexSession() as session:
        query = select(Folder).where(Folder.status == "active")
        if content_type:
            query = query.where(Folder.content_type == content_type)
        if parent_id is not None:
            query = query.where(Folder.parent_id == (parent_id or None))
        rows = list((await session.scalars(query.order_by(Folder.depth, Folder.name))).all())
        return {"items": [folder_dict(row) for row in rows]}


@app.get("/api/folders/{folder_id}", response_model=FolderDetailOutput)
async def folder_detail(
    folder_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    sort: str = "name",
    order: str = "asc",
):
    sort_columns = {"name": Resource.name, "modified_at": Resource.modified_at, "size": Resource.size}
    if sort not in sort_columns or order not in {"asc", "desc"}:
        raise HTTPException(400, {"code": "API-001", "message": "排序参数无效"})
    async with IndexSession() as session:
        row = await session.get(Folder, folder_id)
        if not row or row.status != "active":
            raise HTTPException(404, {"code": "FD-001", "message": "文件夹不存在或已不可用"})
        all_folders = {item.id: item for item in (await session.scalars(select(Folder).where(Folder.status == "active"))).all()}
        child_folders = list((await session.scalars(select(Folder).where(Folder.parent_id == folder_id, Folder.status == "active").order_by(Folder.name))).all())
        resource_query = select(Resource).where(Resource.parent_id == folder_id, Resource.status == "active")
        total = int(await session.scalar(select(func.count()).select_from(Resource).where(Resource.parent_id == folder_id, Resource.status == "active")) or 0)
        order_by = sort_columns[sort].asc() if order == "asc" else sort_columns[sort].desc()
        child_resources = list((await session.scalars(resource_query.order_by(order_by, Resource.id).offset((page - 1) * page_size).limit(page_size))).all())
        return {
            "folder": folder_dict(row),
            "breadcrumbs": breadcrumbs_for(row, all_folders),
            "child_folders": [folder_dict(item) for item in child_folders],
            "resources": {"items": [resource_dict(item, row) for item in child_resources], "page": page, "page_size": page_size, "total": total, "total_pages": math.ceil(total / page_size) if total else 0},
        }


@app.get("/api/search", response_model=SearchOutput)
async def search(
    q: str = "",
    resource_type: str | None = Query(default=None, alias="type"),
    object_type: str = "all",
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    sort: str = "relevance",
):
    normalized = normalize_search_query(q)
    if not normalized:
        raise HTTPException(400, {"code": "SRCH-001", "message": "搜索关键词为空"})
    if len(normalized) > 200:
        raise HTTPException(400, {"code": "SRCH-002", "message": "搜索关键词过长"})
    if resource_type is not None and resource_type not in SEARCH_TYPES:
        raise HTTPException(400, {"code": "SRCH-004", "message": "资源类型无效"})
    if object_type not in SEARCH_OBJECT_TYPES or sort not in SEARCH_SORTS:
        raise HTTPException(400, {"code": "SRCH-004", "message": "搜索参数无效"})
    try:
        async with IndexSession() as session:
            candidates, total = await search_index(session, normalized, resource_type, object_type, page, page_size, sort)
            resource_ids = [row["object_id"] for row in candidates if row["object_type"] == "resource"]
            folder_ids = [row["object_id"] for row in candidates if row["object_type"] == "folder"]
            resources_by_id = {
                row.id: row for row in (await session.scalars(select(Resource).where(Resource.id.in_(resource_ids), Resource.status == "active"))).all()
            } if resource_ids else {}
            folders_by_id = {
                row.id: row for row in (await session.scalars(select(Folder).where(Folder.id.in_(folder_ids), Folder.status == "active"))).all()
            } if folder_ids else {}
            all_folders = {
                row.id: row for row in (await session.scalars(select(Folder).where(Folder.status == "active"))).all()
            }
            items = []
            for candidate in candidates:
                if candidate["object_type"] == "resource":
                    row = resources_by_id.get(candidate["object_id"])
                    if not row:
                        continue
                    parent = all_folders.get(row.parent_id) if row.parent_id else None
                    payload = resource_dict(row, parent)
                    payload.update({
                        "object_type": "resource",
                        "breadcrumbs": breadcrumbs_for(parent, all_folders) if parent else [],
                        "child_folder_count": 0,
                        "resource_count": 0,
                        "match_type": classify_match(row.name, normalized),
                    })
                else:
                    row = folders_by_id.get(candidate["object_id"])
                    if not row:
                        continue
                    payload = folder_dict(row)
                    payload.update({
                        "object_type": "folder",
                        "extension": "",
                        "size": None,
                        "parent": None,
                        "breadcrumbs": breadcrumbs_for(row, all_folders),
                        "thumbnail": "",
                        "match_type": classify_match(row.name, normalized),
                    })
                items.append(payload)
            return {
                "query": normalized,
                "filters": {"type": resource_type, "object_type": object_type, "sort": sort},
                "items": items,
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": math.ceil(total / page_size) if total else 0,
            }
    except HTTPException:
        raise
    except Exception as exc:
        await log_operation("search", "query_failed", type(exc).__name__, level="ERROR")
        raise HTTPException(503, {"code": "SRCH-003", "message": "搜索索引暂时不可用"}) from exc


@app.get("/api/collections")
async def public_collections():
    async with StateSession() as state, IndexSession() as index:
        rows = list((await state.scalars(select(Collection).where(Collection.status == "active").order_by(Collection.sort_order, Collection.name))).all())
        return {"items": [await collection_dict(state, index, row) for row in rows]}


@app.get("/api/collections/{collection_id}")
async def public_collection_detail(collection_id: int):
    async with StateSession() as state, IndexSession() as index:
        row = await state.get(Collection, collection_id)
        if not row or row.status != "active":
            raise HTTPException(404, "合集不存在")
        return await collection_dict(state, index, row, include_items=True)


@app.get("/api/shares/{token}")
async def public_share(token: str):
    async with StateSession() as state, IndexSession() as index:
        row = await state.get(Share, token)
        if not row or not row.enabled or share_is_expired(row):
            raise HTTPException(410, "分享不存在、已关闭或已过期")
        if row.object_type == "resource":
            target = await index.get(Resource, row.object_id)
            if not target or target.status != "active":
                raise HTTPException(404, "分享的资源不存在")
            payload = resource_dict(target)
        elif row.object_type == "folder":
            target = await index.get(Folder, row.object_id)
            if not target or target.status != "active":
                raise HTTPException(404, "分享的文件夹不存在")
            child_folders = list((await index.scalars(select(Folder).where(Folder.parent_id == target.id, Folder.status == "active").order_by(Folder.name))).all())
            child_resources = list((await index.scalars(select(Resource).where(Resource.parent_id == target.id, Resource.status == "active").order_by(Resource.name))).all())
            payload = {"folder": folder_dict(target), "folders": [folder_dict(item) for item in child_folders], "resources": [resource_dict(item) for item in child_resources]}
        else:
            target = await state.get(Collection, int(row.object_id)) if row.object_id.isdigit() else None
            if not target:
                raise HTTPException(404, "分享的合集不存在")
            payload = await collection_dict(state, index, target, include_items=True)
        row.access_count += 1
        row.last_accessed_at = utcnow()
        await state.commit()
        return {"share": share_dict(row), "target": payload}


@app.get("/d/{resource_id}")
async def download(resource_id: str):
    started = time.perf_counter()
    async with IndexSession() as index, StateSession() as state:
        if not validate_resource_id(resource_id):
            await _download_event(state, resource_id[:64], "failed", "DL-001", started)
            return _download_error_redirect("DL-001", resource_id[:64])
        resource = await index.get(Resource, resource_id)
        if not resource or resource.status == "missing":
            await _download_event(state, resource_id, "failed", "DL-001", started)
            return _download_error_redirect("DL-001", resource_id)
        if resource.status != "active":
            await _download_event(state, resource_id, "failed", "DL-007", started)
            return _download_error_redirect("DL-007", resource_id)
        connection = await state.get(AListConnection, 1)
        try:
            resolution = await resolve_download_entry(resource, connection)
            await _download_event(state, resource_id, "success", None, started)
            return RedirectResponse(resolution.url, status_code=302)
        except DownloadError as exc:
            await _download_event(state, resource_id, "failed", exc.code, started)
            return _download_error_redirect(exc.code, resource_id)


def _download_error_redirect(code: str, resource_id: str) -> RedirectResponse:
    return RedirectResponse(f"/download-error?{urlencode({'code': code, 'resource': resource_id})}", status_code=302)


async def _download_event(session, resource_id, result, code, started, source: str = "public"):
    session.add(DownloadEvent(resource_id=resource_id, result=result, error_code=code, duration_ms=int((time.perf_counter() - started) * 1000), source=source))
    await session.commit()


@app.get("/p/{resource_id}")
async def preview(resource_id: str, refresh: bool = False):
    if not validate_resource_id(resource_id):
        return _preview_error_redirect(resource_id[:64], "PV-001")
    async with IndexSession() as index, StateSession() as state:
        resource = await index.get(Resource, resource_id)
        if not resource or resource.status != "active":
            return _preview_error_redirect(resource_id, "PV-001")
        connection = await state.get(AListConnection, 1)
        try:
            resolution = await resolve_preview_url(resource, connection, force_refresh=refresh)
            return RedirectResponse(resolution.url, status_code=302)
        except PreviewError as exc:
            return _preview_error_redirect(resource.id, exc.code)


def _preview_error_redirect(resource_id: str, code: str) -> RedirectResponse:
    return RedirectResponse(f"/resource/{resource_id}?{urlencode({'preview_error': code})}", status_code=302)


@app.get("/api/admin/overview")
async def admin_overview():
    async with StateSession() as state, IndexSession() as index:
        resource_total = int(await index.scalar(select(func.count()).select_from(Resource).where(Resource.status == "active")) or 0)
        folder_total = int(await index.scalar(select(func.count()).select_from(Folder).where(Folder.status == "active")) or 0)
        failures = int(await state.scalar(select(func.count()).select_from(DownloadEvent).where(DownloadEvent.result == "failed")) or 0)
        connection = await state.get(AListConnection, 1)
        latest_sync = await index.scalar(select(SyncRun).order_by(desc(SyncRun.id)).limit(1))
        logs = list((await state.scalars(select(OperationLog).order_by(desc(OperationLog.id)).limit(6))).all())
        type_counts = {}
        for kind in ("software", "image", "video", "document", "file"):
            type_counts[kind] = int(await index.scalar(select(func.count()).select_from(Resource).where(Resource.content_type == kind, Resource.status == "active")) or 0)
        circuit = await sync_circuit_status()
        return {
            "resources": resource_total,
            "folders": folder_total,
            "download_failures": failures,
            "alist_connected": bool(connection and connection.enabled and connection.last_test_status == "success"),
            "latest_sync": None if not latest_sync else {
                "id": latest_sync.id,
                "status": latest_sync.status,
                "finished_at": latest_sync.finished_at,
                "added": latest_sync.added_count,
                "updated": latest_sync.updated_count,
                "removed": latest_sync.removed_count,
                "folders_scanned": latest_sync.folders_scanned,
                "resources_scanned": latest_sync.resources_scanned,
                "current_path": latest_sync.current_path,
                "roots_total": latest_sync.roots_total,
                "roots_completed": latest_sync.roots_completed,
                "roots_failed": latest_sync.roots_failed,
                "duration_ms": latest_sync.duration_ms,
            },
            "sync_circuit": {
                "open": circuit["open"],
                "until": circuit["until"],
                "reason": circuit["reason"],
            },
            "type_counts": type_counts,
            "logs": [{"level": row.level, "message": row.message, "created_at": row.created_at} for row in logs],
        }


def download_diagnostic_dict(row: DownloadDiagnostic) -> dict:
    return {
        "id": row.id,
        "resource_id": row.resource_id,
        "status": row.status,
        "failed_step": row.failed_step,
        "error_code": row.error_code,
        "message": row.message,
        "duration_ms": row.duration_ms,
        "target_host": row.target_host,
        "created_at": row.created_at,
    }


@app.post("/api/admin/downloads/diagnose")
async def diagnose_download(payload: DownloadDiagnosticInput):
    started = time.perf_counter()
    steps: list[dict] = []
    async with IndexSession() as index, StateSession() as state:
        resource = await index.get(Resource, payload.resource_id)
        if not resource:
            steps.append({"name": "resource_lookup", "status": "failed", "duration_ms": 0})
            diagnostic = DownloadDiagnostic(resource_id=payload.resource_id, status="failed", failed_step="resource_lookup", error_code="DL-001", message="资源不存在或已失效", duration_ms=int((time.perf_counter() - started) * 1000))
            state.add(diagnostic)
            await state.commit()
            return {**download_diagnostic_dict(diagnostic), "resource_name": "", "has_sign": False, "base_path": "", "steps": steps}
        steps.append({"name": "resource_lookup", "status": "success", "duration_ms": 0})
        if resource.status != "active":
            code = "DL-001" if resource.status == "missing" else "DL-007"
            steps.append({"name": "resource_status", "status": "failed", "duration_ms": 0})
            diagnostic = DownloadDiagnostic(resource_id=resource.id, status="failed", failed_step="resource_status", error_code=code, message="资源不存在或当前禁止下载", duration_ms=int((time.perf_counter() - started) * 1000))
            state.add(diagnostic)
            await state.commit()
            return {**download_diagnostic_dict(diagnostic), "resource_name": resource.name, "has_sign": False, "base_path": "", "steps": steps}
        steps.append({"name": "resource_status", "status": "success", "duration_ms": 0})
        connection = await state.get(AListConnection, 1)
        try:
            resolution = await resolve_download_entry(resource, connection)
            steps.extend(resolution.steps)
            diagnostic = DownloadDiagnostic(resource_id=resource.id, status="success", message="下载跳转已就绪", duration_ms=int((time.perf_counter() - started) * 1000), target_host=resolution.target_host)
            state.add(diagnostic)
            await state.commit()
            return {**download_diagnostic_dict(diagnostic), "resource_name": resource.name, "has_sign": resolution.has_sign, "base_path": resolution.base_path, "steps": steps}
        except DownloadError as exc:
            steps.append({"name": exc.failed_step, "status": "failed", "duration_ms": int((time.perf_counter() - started) * 1000)})
            diagnostic = DownloadDiagnostic(resource_id=resource.id, status="failed", failed_step=exc.failed_step, error_code=exc.code, message=exc.message, duration_ms=int((time.perf_counter() - started) * 1000))
            state.add(diagnostic)
            await state.commit()
            return {**download_diagnostic_dict(diagnostic), "resource_name": resource.name, "has_sign": False, "base_path": "", "steps": steps}


@app.get("/api/admin/downloads/diagnostics")
async def download_diagnostic_history(limit: int = Query(20, ge=1, le=100)):
    async with StateSession() as session:
        rows = list((await session.scalars(select(DownloadDiagnostic).order_by(desc(DownloadDiagnostic.id)).limit(limit))).all())
        return {"items": [download_diagnostic_dict(row) for row in rows]}


@app.get("/api/admin/alist")
async def get_alist():
    async with StateSession() as session:
        row = await session.get(AListConnection, 1)
        if not row:
            return {"base_url": "", "username": "", "remember_credentials": True, "enabled": False, "connection_status": "unconfigured", "last_test_status": "untested", "last_test_message": "", "last_test_at": None, "has_password": False}
        return {"base_url": row.base_url, "username": row.username, "remember_credentials": row.remember_credentials, "enabled": row.enabled, "connection_status": "connected" if row.enabled and row.last_test_status == "success" else "disconnected", "last_test_status": row.last_test_status, "last_test_message": row.last_test_message, "last_test_at": row.last_test_at, "has_password": bool(row.password_ciphertext)}


@app.post("/api/admin/alist/test")
async def test_alist(payload: AListInput):
    async with StateSession() as session:
        row = await session.get(AListConnection, 1)
        password = payload.password
        try:
            if not password and row and row.password_ciphertext:
                password = decrypt_secret(row.password_ciphertext)
            if not password:
                raise AListError("请输入 AList 密码", "AL-004", status_code=400, auth_failed=True)
            result = await AListClient(payload.base_url, payload.username, password).test()
        except Exception as exc:
            status_row = row or AListConnection(id=1)
            status_row.last_test_status = "failed"
            status_row.last_test_message = str(exc)
            status_row.last_test_at = utcnow()
            session.add(status_row)
            session.add(OperationLog(level="ERROR", module="alist", action="test", message=f"AList 连接测试失败：{str(exc)[:300]}"))
            await session.commit()
            raise alist_http_exception(exc, 400) from exc
        status_row = row or AListConnection(id=1)
        status_row.last_test_status = "success"
        status_row.last_test_message = result["message"]
        status_row.last_test_at = utcnow()
        status_row.base_path = result.get("base_path") or "/"
        session.add(status_row)
        session.add(OperationLog(module="alist", action="test", message=f"AList 连接测试成功，根目录包含 {result['item_count']} 项"))
        await session.commit()
        return result


@app.put("/api/admin/alist")
async def save_alist(payload: AListInput):
    async with StateSession() as session:
        row = await session.get(AListConnection, 1) or AListConnection(id=1)
        password = payload.password
        if not password and row.password_ciphertext:
            try:
                password = decrypt_secret(row.password_ciphertext)
            except ValueError as exc:
                raise alist_http_exception(exc, 400) from exc
        if not password:
            raise HTTPException(400, "请输入 AList 密码")
        try:
            result = await AListClient(payload.base_url, payload.username, password).test()
        except Exception as exc:
            row.last_test_status = "failed"
            row.last_test_message = str(exc)
            row.last_test_at = utcnow()
            session.add(row)
            await session.commit()
            session.add(OperationLog(level="ERROR", module="alist", action="save", message=f"AList 设置验证失败：{str(exc)[:300]}"))
            await session.commit()
            raise alist_http_exception(exc, 400) from exc
        row.base_url = payload.base_url.rstrip("/")
        row.base_path = result.get("base_path") or "/"
        row.username = payload.username
        row.password_ciphertext = encrypt_secret(password) if payload.remember_credentials else ""
        row.remember_credentials = payload.remember_credentials
        row.enabled = True
        row.last_test_status = "success"
        row.last_test_message = "AList 连接及根目录访问成功"
        row.last_test_at = utcnow()
        session.add(row)
        session.add(OperationLog(module="alist", action="save", message="AList 连接设置已验证并保存"))
        await session.commit()
        return {"ok": True, "message": "AList 设置已保存"}


@app.get("/api/admin/alist/directories")
async def browse_alist_directories(path: str = Query("/", min_length=1, max_length=1000)):
    normalized_path = "/" + path.strip().strip("/")
    if normalized_path == "//":
        normalized_path = "/"
    async with StateSession() as session:
        row = await session.get(AListConnection, 1)
    if not row or not row.enabled:
        raise HTTPException(409, "请先连接并保存 AList 设置")
    if not row.password_ciphertext:
        raise HTTPException(409, "当前未保存 AList 登录凭据，请重新保存连接并启用记住登录信息")
    try:
        client = AListClient(row.base_url, row.username, decrypt_secret(row.password_ciphertext))
        directories = await client.list_directories(normalized_path)
    except Exception as exc:
        raise alist_http_exception(exc) from exc

    def directory_path(name: str) -> str:
        return f"/{name}" if normalized_path == "/" else f"{normalized_path}/{name}"

    parent_path = "/" if normalized_path == "/" else normalized_path.rsplit("/", 1)[0] or "/"
    return {
        "path": normalized_path,
        "parent_path": parent_path,
        "items": [
            {
                "name": str(item["name"]),
                "path": directory_path(str(item["name"])),
                "modified": item.get("modified"),
            }
            for item in directories
        ],
    }


@app.get("/api/admin/root-mappings")
async def get_root_mappings():
    async with StateSession() as session:
        rows = list((await session.scalars(select(ContentRootMapping).order_by(ContentRootMapping.sort_order))).all())
        return {"items": [{"id": row.id, "content_type": row.content_type, "display_name": row.display_name, "alist_path": row.alist_path, "enabled": row.enabled, "sort_order": row.sort_order} for row in rows]}


async def validate_root_mapping_path(path: str) -> str:
    normalized = normalize_path(path)
    async with StateSession() as session:
        connection = await session.get(AListConnection, 1)
    if not connection or not connection.enabled or not connection.password_ciphertext:
        raise HTTPException(409, "请先保存可用的 AList 连接和凭据")
    try:
        client = AListClient(connection.base_url, connection.username, decrypt_secret(connection.password_ciphertext))
        info = await client.get_path(normalized)
    except Exception as exc:
        raise alist_http_exception(exc) from exc
    if info.get("is_dir") is False:
        raise HTTPException(400, "根目录映射必须指向 AList 文件夹")
    return normalized


@app.post("/api/admin/root-mappings")
async def add_root_mapping(payload: RootMappingInput):
    normalized_path = await validate_root_mapping_path(payload.alist_path)
    async with StateSession() as session:
        row = ContentRootMapping(**{**payload.model_dump(), "alist_path": normalized_path})
        session.add(row)
        try:
            await session.commit()
        except Exception as exc:
            await session.rollback()
            raise HTTPException(409, "该 AList 根目录已存在") from exc
        await session.refresh(row)
        return {"id": row.id}


@app.put("/api/admin/root-mappings/{mapping_id}")
async def update_root_mapping(mapping_id: int, payload: RootMappingInput):
    normalized_path = await validate_root_mapping_path(payload.alist_path)
    async with StateSession() as session:
        row = await session.get(ContentRootMapping, mapping_id)
        if not row:
            raise HTTPException(404, "映射不存在")
        for key, value in {**payload.model_dump(), "alist_path": normalized_path}.items():
            setattr(row, key, value)
        try:
            await session.commit()
        except Exception as exc:
            await session.rollback()
            raise HTTPException(409, "该 AList 根目录已被其他映射使用") from exc
        return {"ok": True}


@app.delete("/api/admin/root-mappings/{mapping_id}")
async def delete_root_mapping(mapping_id: int):
    async with StateSession() as session:
        row = await session.get(ContentRootMapping, mapping_id)
        if not row:
            raise HTTPException(404, "映射不存在")
        await session.delete(row)
        await session.commit()
        return {"ok": True}


@app.post("/api/admin/sync", status_code=202)
async def sync(payload: SyncInput):
    global manual_sync_task
    if manual_sync_task and not manual_sync_task.done():
        return {"status": "already_running"}
    preflight = await sync_preflight("manual", payload.force)
    if preflight:
        return preflight
    manual_sync_task = asyncio.create_task(
        _run_manual_sync_in_background(payload.full, payload.force),
        name="cloudsite-manual-sync",
    )
    return {"status": "accepted", "message": "同步任务已启动"}


@app.post("/api/admin/search/rebuild")
async def rebuild_public_search_index():
    async with IndexSession() as session:
        folders = list((await session.scalars(select(Folder).where(Folder.status == "active"))).all())
        resources = list((await session.scalars(select(Resource).where(Resource.status == "active"))).all())
        count = await rebuild_search_index(session, folders, resources)
        await session.commit()
    await log_operation("search", "rebuild", f"搜索索引重建完成：{count} 个对象")
    return {"ok": True, "indexed": count, "folders": len(folders), "resources": len(resources)}


def sync_run_dict(row: SyncRun) -> dict:
    return {
        "id": row.id,
        "sync_type": row.sync_type,
        "status": row.status,
        "folders_scanned": row.folders_scanned,
        "resources_scanned": row.resources_scanned,
        "added_count": row.added_count,
        "updated_count": row.updated_count,
        "removed_count": row.removed_count,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
        "duration_ms": row.duration_ms,
        "error_message": row.error_message,
        "current_path": row.current_path,
        "roots_total": row.roots_total,
        "roots_completed": row.roots_completed,
        "roots_failed": row.roots_failed,
    }


@app.get("/api/admin/index/summary")
async def admin_index_summary():
    async with IndexSession() as session:
        latest = await session.scalar(select(SyncRun).order_by(desc(SyncRun.id)).limit(1))
        return {
            "folders": int(await session.scalar(select(func.count()).select_from(Folder).where(Folder.status == "active")) or 0),
            "resources": int(await session.scalar(select(func.count()).select_from(Resource).where(Resource.status == "active")) or 0),
            "latest_sync": sync_run_dict(latest) if latest else None,
            "syncing": bool(latest and latest.status == "running"),
        }


@app.get("/api/admin/index/folders")
async def admin_index_folders():
    async with IndexSession() as session:
        rows = list((await session.scalars(select(Folder).where(Folder.status == "active").order_by(Folder.depth, Folder.path))).all())
        return {"items": [folder_dict(row, include_path=True) for row in rows]}


@app.get("/api/admin/index/folders/{folder_id}")
async def admin_index_folder_detail(folder_id: str):
    async with IndexSession() as session:
        row = await session.get(Folder, folder_id)
        if not row or row.status != "active":
            raise HTTPException(404, "索引目录不存在")
        resources_count = int(await session.scalar(select(func.count()).select_from(Resource).where(Resource.parent_id == row.id, Resource.status == "active")) or 0)
        return {**folder_dict(row, include_path=True), "direct_resource_count": resources_count}


@app.get("/api/admin/sync-runs")
async def admin_sync_runs(limit: int = Query(10, ge=1, le=100)):
    async with IndexSession() as session:
        rows = list((await session.scalars(select(SyncRun).order_by(desc(SyncRun.id)).limit(limit))).all())
        return {"items": [sync_run_dict(row) for row in rows]}


@app.get("/api/admin/sync-runs/{run_id}/changes")
async def admin_sync_changes(run_id: int, limit: int = Query(100, ge=1, le=500)):
    async with IndexSession() as session:
        if not await session.get(SyncRun, run_id):
            raise HTTPException(404, "同步记录不存在")
        rows = list((await session.scalars(select(SyncChange).where(SyncChange.sync_run_id == run_id).order_by(desc(SyncChange.id)).limit(limit))).all())
        return {"items": [{"id": row.id, "object_type": row.object_type, "object_id": row.object_id, "change_type": row.change_type, "old_path": row.old_path, "new_path": row.new_path, "created_at": row.created_at} for row in rows]}


@app.get("/api/admin/collections")
async def admin_collections():
    async with StateSession() as state, IndexSession() as index:
        rows = list((await state.scalars(select(Collection).order_by(Collection.sort_order, desc(Collection.updated_at)))).all())
        return {"items": [await collection_dict(state, index, row) for row in rows]}


@app.get("/api/admin/collections/{collection_id}")
async def admin_collection_detail(collection_id: int):
    async with StateSession() as state, IndexSession() as index:
        row = await state.get(Collection, collection_id)
        if not row:
            raise HTTPException(404, "合集不存在")
        items = list((await state.scalars(select(CollectionItem).where(CollectionItem.collection_id == collection_id).order_by(CollectionItem.sort_order, CollectionItem.id))).all())
        resource_ids = [item.resource_id for item in items]
        resources_by_id = {}
        if resource_ids:
            resources_by_id = {resource.id: resource for resource in (await index.scalars(select(Resource).where(Resource.id.in_(resource_ids)))).all()}
        payload = {
            "id": row.id,
            "name": row.name,
            "description": row.description,
            "cover": row.cover,
            "status": row.status,
            "visible_on_home": row.visible_on_home,
            "sort_order": row.sort_order,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "items": [],
        }
        for item in items:
            resource = resources_by_id.get(item.resource_id)
            if resource and resource.status == "active":
                payload["items"].append({"resource_id": item.resource_id, "name": resource.name, "content_type": resource.content_type, "extension": resource.extension, "size": resource.size, "active": True})
            else:
                payload["items"].append({"resource_id": item.resource_id, "name": None, "content_type": "", "extension": "", "size": 0, "active": False})
        return payload


@app.post("/api/admin/collections")
async def create_collection(payload: CollectionInput):
    async with StateSession() as session:
        row = Collection(**payload.model_dump())
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return {"id": row.id}


@app.put("/api/admin/collections/{collection_id}")
async def update_collection(collection_id: int, payload: CollectionInput):
    async with StateSession() as session:
        row = await session.get(Collection, collection_id)
        if not row:
            raise HTTPException(404, "合集不存在")
        for key, value in payload.model_dump().items():
            setattr(row, key, value)
        await session.commit()
        return {"ok": True}


@app.put("/api/admin/collections/{collection_id}/items")
async def set_collection_items(collection_id: int, payload: CollectionItemsInput):
    async with StateSession() as state, IndexSession() as index:
        if not await state.get(Collection, collection_id):
            raise HTTPException(404, "合集不存在")
        resource_ids = list(dict.fromkeys(payload.resource_ids))
        if resource_ids:
            existing = set((await index.scalars(select(Resource.id).where(Resource.id.in_(resource_ids), Resource.status == "active"))).all())
            missing = [resource_id for resource_id in resource_ids if resource_id not in existing]
            if missing:
                raise HTTPException(400, f"资源不存在：{', '.join(missing[:5])}")
        await state.execute(delete(CollectionItem).where(CollectionItem.collection_id == collection_id))
        state.add_all([CollectionItem(collection_id=collection_id, resource_id=resource_id, sort_order=position) for position, resource_id in enumerate(resource_ids)])
        await state.commit()
        return {"ok": True, "item_count": len(resource_ids)}


@app.delete("/api/admin/collections/{collection_id}")
async def delete_collection(collection_id: int):
    async with StateSession() as session:
        row = await session.get(Collection, collection_id)
        if not row:
            raise HTTPException(404, "合集不存在")
        await session.delete(row)
        await session.commit()
        return {"ok": True}


@app.get("/api/admin/shares")
async def admin_shares():
    async with StateSession() as state, IndexSession() as index:
        rows = list((await state.scalars(select(Share).order_by(desc(Share.created_at)))).all())
        resource_ids = [row.object_id for row in rows if row.object_type == "resource"]
        folder_ids = [row.object_id for row in rows if row.object_type == "folder"]
        collection_ids = [int(row.object_id) for row in rows if row.object_type == "collection" and row.object_id.isdigit()]
        names: dict[str, str] = {}
        if resource_ids:
            names.update({row.id: row.name for row in (await index.scalars(select(Resource).where(Resource.id.in_(resource_ids)))).all()})
        if folder_ids:
            names.update({row.id: row.name for row in (await index.scalars(select(Folder).where(Folder.id.in_(folder_ids)))).all()})
        if collection_ids:
            names.update({str(row.id): row.name for row in (await state.scalars(select(Collection).where(Collection.id.in_(collection_ids)))).all()})
        return {"items": [share_dict(row) | {"expired": share_is_expired(row), "target_name": names.get(row.object_id)} for row in rows]}


@app.post("/api/admin/shares")
async def create_share(payload: ShareInput):
    token = secrets.token_urlsafe(12)
    async with StateSession() as state, IndexSession() as index:
        if payload.object_type == "resource":
            target = await index.get(Resource, payload.object_id)
        elif payload.object_type == "folder":
            target = await index.get(Folder, payload.object_id)
        else:
            target = await state.get(Collection, int(payload.object_id)) if payload.object_id.isdigit() else None
        if not target or getattr(target, "status", "active") != "active":
            raise HTTPException(400, "分享对象不存在或不可用")
        row = Share(token=token, **payload.model_dump())
        state.add(row)
        await state.commit()
        return share_dict(row)


@app.patch("/api/admin/shares/{token}")
async def update_share(token: str, payload: ShareUpdate):
    async with StateSession() as session:
        row = await session.get(Share, token)
        if not row:
            raise HTTPException(404, "分享不存在")
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(row, key, value)
        await session.commit()
        return share_dict(row)


@app.delete("/api/admin/shares/{token}")
async def delete_share(token: str):
    async with StateSession() as session:
        row = await session.get(Share, token)
        if not row:
            raise HTTPException(404, "分享不存在")
        await session.delete(row)
        await session.commit()
        return {"ok": True}


@app.get("/api/admin/system")
async def get_system():
    async with StateSession() as state, IndexSession() as index:
        values = await get_system_values(state)
        values.update({
            "version": __version__,
            "database": "SQLite 3",
            "timezone": "Asia/Shanghai",
            "resources": int(await index.scalar(select(func.count()).select_from(Resource).where(Resource.status == "active")) or 0),
            "folders": int(await index.scalar(select(func.count()).select_from(Folder).where(Folder.status == "active")) or 0),
        })
        return values


@app.put("/api/admin/system")
async def save_system(payload: SystemInput):
    async with StateSession() as session:
        for key, value in payload.model_dump().items():
            row = await session.get(SystemSetting, key) or SystemSetting(key=key)
            row.value = str(value).lower() if isinstance(value, bool) else str(value)
            session.add(row)
        await session.commit()
        return {"ok": True}


@app.get("/api/admin/site")
async def get_site():
    async with StateSession() as session:
        row = await session.get(SiteSettings, 1)
        return {"site_name": row.site_name, "home_title": row.home_title, "description": row.description}


@app.put("/api/admin/site")
async def save_site(payload: SiteInput):
    async with StateSession() as session:
        row = await session.get(SiteSettings, 1) or SiteSettings(id=1)
        row.site_name, row.home_title, row.description = payload.site_name, payload.home_title, payload.description
        session.add(row)
        await session.commit()
        return {"ok": True}
