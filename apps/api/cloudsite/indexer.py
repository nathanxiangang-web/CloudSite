import asyncio
import hashlib
import mimetypes
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any, Awaitable, Callable

from sqlalchemy import delete, select, update

from .alist import AListClient
from .crypto import decrypt_secret
from .database import IndexSession, StateSession
from .models import AListConnection, ContentRootMapping, Folder, OperationLog, Resource, SyncChange, SyncRun
from .search import rebuild_search_index


sync_lock = asyncio.Lock()


def normalize_path(value: str) -> str:
    path = str(value or "").strip().replace("\\", "/")
    path = re.sub(r"/+", "/", f"/{path.lstrip('/')}")
    return path.rstrip("/") or "/"


def stable_id(kind: str, path: str) -> str:
    normalized = normalize_path(path)
    prefix = "f_" if kind == "folder" else "r_"
    return prefix + hashlib.sha256(f"{kind}:{normalized}".encode("utf-8")).hexdigest()[:32]


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def join_path(parent: str, name: str) -> str:
    return normalize_path(f"{normalize_path(parent)}/{str(name).strip('/')}")


def should_ignore(path: str) -> bool:
    return any(part == ".cloudsite" for part in PurePosixPath(normalize_path(path)).parts)


def times_equal(left: datetime | None, right: datetime | None) -> bool:
    if left is None or right is None:
        return left is right
    normalized_left = left if left.tzinfo else left.replace(tzinfo=timezone.utc)
    normalized_right = right if right.tzinfo else right.replace(tzinfo=timezone.utc)
    return abs(normalized_left.timestamp() - normalized_right.timestamp()) < 0.001


@dataclass(slots=True)
class ScannedFolder:
    id: str
    name: str
    path: str
    parent_id: str | None
    content_type: str
    root_mapping_id: int
    depth: int
    modified_at: datetime | None
    child_folder_count: int = 0
    resource_count: int = 0


@dataclass(slots=True)
class ScannedResource:
    id: str
    name: str
    path: str
    parent_id: str
    content_type: str
    root_mapping_id: int
    extension: str
    mime_type: str
    size: int
    modified_at: datetime | None
    thumbnail: str


async def load_client_and_roots() -> tuple[AListClient, list[ContentRootMapping]]:
    async with StateSession() as session:
        connection = await session.get(AListConnection, 1)
        if not connection or not connection.enabled:
            raise RuntimeError("尚未保存可用的 AList 连接")
        if not connection.password_ciphertext:
            raise RuntimeError("AList 凭据未保存，无法执行后台同步")
        roots = list(
            (
                await session.scalars(
                    select(ContentRootMapping)
                    .where(ContentRootMapping.enabled.is_(True))
                    .order_by(ContentRootMapping.sort_order, ContentRootMapping.id)
                )
            ).all()
        )
        if not roots:
            raise RuntimeError("尚未配置内容根目录映射")
        return AListClient(
            connection.base_url,
            connection.username,
            decrypt_secret(connection.password_ciphertext),
        ), roots


async def recover_interrupted_sync_runs() -> None:
    """Mark unfinished rows only during API startup, before any new task can begin."""
    async with IndexSession() as session:
        await session.execute(
            update(SyncRun)
            .where(SyncRun.status == "running")
            .values(
                status="failed",
                finished_at=datetime.now(timezone.utc),
                error_message="同步任务被服务重启或异常中断",
            )
        )
        await session.commit()


async def scan_roots(
    client: AListClient,
    roots: list[ContentRootMapping],
    progress: Callable[[int, int], Awaitable[None]] | None = None,
) -> tuple[dict[str, ScannedFolder], dict[str, ScannedResource]]:
    folders: dict[str, ScannedFolder] = {}
    resources: dict[str, ScannedResource] = {}
    for root in roots:
        root_path = normalize_path(root.alist_path)
        root_id = stable_id("folder", root_path)
        folders[root_id] = ScannedFolder(
            id=root_id,
            name=PurePosixPath(root_path).name or root.display_name,
            path=root_path,
            parent_id=None,
            content_type=root.content_type,
            root_mapping_id=root.id,
            depth=0,
            modified_at=None,
        )
        queue: list[tuple[str, str, int]] = [(root_path, root_id, 1)]
        cursor = 0
        while cursor < len(queue):
            current_path, parent_id, depth = queue[cursor]
            cursor += 1
            entries = await client.list_path(current_path)
            for item in entries:
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                path = join_path(current_path, name)
                if should_ignore(path):
                    continue
                modified = parse_time(item.get("modified") or item.get("updated_at"))
                if item.get("is_dir"):
                    object_id = stable_id("folder", path)
                    folders[object_id] = ScannedFolder(
                        id=object_id,
                        name=name,
                        path=path,
                        parent_id=parent_id,
                        content_type=root.content_type,
                        root_mapping_id=root.id,
                        depth=depth,
                        modified_at=modified,
                    )
                    queue.append((path, object_id, depth + 1))
                else:
                    object_id = stable_id("resource", path)
                    extension = PurePosixPath(name).suffix.lower().lstrip(".")
                    resources[object_id] = ScannedResource(
                        id=object_id,
                        name=name,
                        path=path,
                        parent_id=parent_id,
                        content_type=root.content_type,
                        root_mapping_id=root.id,
                        extension=extension,
                        mime_type=str(item.get("type") or mimetypes.guess_type(name)[0] or "application/octet-stream"),
                        size=int(item.get("size") or 0),
                        modified_at=modified,
                        thumbnail=str(item.get("thumb") or item.get("thumbnail") or ""),
                    )
            if progress:
                await progress(len(folders), len(resources))

    for folder in folders.values():
        if folder.parent_id and folder.parent_id in folders:
            folders[folder.parent_id].child_folder_count += 1
    for resource in resources.values():
        if resource.parent_id in folders:
            folders[resource.parent_id].resource_count += 1
    return folders, resources


def folder_changed(row: Folder, item: ScannedFolder) -> bool:
    return any(
        (
            row.name != item.name,
            row.path != item.path,
            row.parent_id != item.parent_id,
            row.content_type != item.content_type,
            row.root_mapping_id != item.root_mapping_id,
            row.depth != item.depth,
            not times_equal(row.modified_at, item.modified_at),
            row.child_folder_count != item.child_folder_count,
            row.resource_count != item.resource_count,
            row.status != "active",
        )
    )


def resource_changed(row: Resource, item: ScannedResource) -> bool:
    return any(
        (
            row.name != item.name,
            row.path != item.path,
            row.parent_id != item.parent_id,
            row.content_type != item.content_type,
            row.root_mapping_id != item.root_mapping_id,
            row.extension != item.extension,
            row.mime_type != item.mime_type,
            row.size != item.size,
            not times_equal(row.modified_at, item.modified_at),
            row.thumbnail != item.thumbnail,
            row.status != "active",
        )
    )


def preserve_existing_ids(
    folders: dict[str, ScannedFolder],
    resources: dict[str, ScannedResource],
    existing_folders: dict[str, Folder],
    existing_resources: dict[str, Resource],
) -> tuple[dict[str, ScannedFolder], dict[str, ScannedResource]]:
    """Keep pre-M2 IDs for the same path so existing collection/share references remain valid."""
    folder_by_path = {row.path: row for row in existing_folders.values()}
    resource_by_path = {row.path: row for row in existing_resources.values()}
    folder_id_map: dict[str, str] = {}
    for item in folders.values():
        existing = folder_by_path.get(item.path)
        if existing and existing.id != item.id:
            folder_id_map[item.id] = existing.id
            item.id = existing.id
    for item in folders.values():
        if item.parent_id:
            item.parent_id = folder_id_map.get(item.parent_id, item.parent_id)
    for item in resources.values():
        item.parent_id = folder_id_map.get(item.parent_id, item.parent_id)
        existing = resource_by_path.get(item.path)
        if existing:
            item.id = existing.id
    return {item.id: item for item in folders.values()}, {item.id: item for item in resources.values()}


async def run_sync(sync_type: str = "manual", full: bool = False) -> dict[str, Any]:
    if sync_lock.locked():
        raise RuntimeError("已有同步任务正在运行")
    async with sync_lock:
        started = time.perf_counter()
        async with IndexSession() as session:
            running = await session.scalar(select(SyncRun.id).where(SyncRun.status == "running").limit(1))
            if running:
                raise RuntimeError("已有同步任务正在运行")
            run = SyncRun(sync_type="full" if full else sync_type, status="running")
            session.add(run)
            await session.commit()
            await session.refresh(run)
            run_id = run.id
            try:
                client, roots = await load_client_and_roots()
                last_progress_at = 0.0

                async def update_progress(folder_count: int, resource_count: int) -> None:
                    nonlocal last_progress_at
                    current = time.monotonic()
                    if current - last_progress_at < 1.0:
                        return
                    await session.execute(
                        update(SyncRun)
                        .where(SyncRun.id == run_id)
                        .values(folders_scanned=folder_count, resources_scanned=resource_count)
                    )
                    await session.commit()
                    last_progress_at = current

                async with client:
                    scanned_folders, scanned_resources = await scan_roots(client, roots, update_progress)
                existing_folders = {row.id: row for row in (await session.scalars(select(Folder))).all()}
                existing_resources = {row.id: row for row in (await session.scalars(select(Resource))).all()}
                scanned_folders, scanned_resources = preserve_existing_ids(
                    scanned_folders,
                    scanned_resources,
                    existing_folders,
                    existing_resources,
                )

                if full:
                    await session.execute(delete(Folder))
                    await session.execute(delete(Resource))
                    existing_folders = {}
                    existing_resources = {}

                added = updated = removed = 0
                now = datetime.now(timezone.utc)
                for object_id, item in scanned_folders.items():
                    row = existing_folders.get(object_id)
                    if row is None:
                        row = Folder(id=object_id)
                        session.add(row)
                        session.add(SyncChange(sync_run_id=run.id, object_type="folder", object_id=object_id, change_type="added", new_path=item.path))
                        added += 1
                    elif folder_changed(row, item):
                        session.add(SyncChange(sync_run_id=run.id, object_type="folder", object_id=object_id, change_type="updated", old_path=row.path, new_path=item.path))
                        updated += 1
                    _apply_folder(row, item, now)

                for object_id, item in scanned_resources.items():
                    row = existing_resources.get(object_id)
                    if row is None:
                        row = Resource(id=object_id)
                        session.add(row)
                        session.add(SyncChange(sync_run_id=run.id, object_type="resource", object_id=object_id, change_type="added", new_path=item.path))
                        added += 1
                    elif resource_changed(row, item):
                        session.add(SyncChange(sync_run_id=run.id, object_type="resource", object_id=object_id, change_type="updated", old_path=row.path, new_path=item.path))
                        updated += 1
                    _apply_resource(row, item, now)

                if not full:
                    for object_id, row in existing_folders.items():
                        if row.status == "active" and object_id not in scanned_folders:
                            row.status = "missing"
                            row.indexed_at = now
                            session.add(SyncChange(sync_run_id=run.id, object_type="folder", object_id=object_id, change_type="removed", old_path=row.path))
                            removed += 1
                    for object_id, row in existing_resources.items():
                        if row.status == "active" and object_id not in scanned_resources:
                            row.status = "missing"
                            row.indexed_at = now
                            session.add(SyncChange(sync_run_id=run.id, object_type="resource", object_id=object_id, change_type="removed", old_path=row.path))
                            removed += 1

                await rebuild_search_index(session, scanned_folders.values(), scanned_resources.values())
                run.status = "success"
                run.folders_scanned = len(scanned_folders)
                run.resources_scanned = len(scanned_resources)
                run.added_count = added
                run.updated_count = updated
                run.removed_count = removed
                run.finished_at = now
                run.duration_ms = int((time.perf_counter() - started) * 1000)
                await session.commit()
                await log_operation("sync", "completed", f"同步完成：{len(scanned_folders)} 个文件夹，{len(scanned_resources)} 个资源；新增 {added}，修改 {updated}，移除 {removed}")
                return {
                    "id": run.id,
                    "status": run.status,
                    "folders": len(scanned_folders),
                    "resources": len(scanned_resources),
                    "added": added,
                    "updated": updated,
                    "removed": removed,
                    "duration_ms": run.duration_ms,
                }
            except Exception as exc:
                await session.rollback()
                failed_run = await session.get(SyncRun, run_id)
                if failed_run:
                    failed_run.status = "failed"
                    failed_run.error_message = str(exc)[:1000]
                    failed_run.finished_at = datetime.now(timezone.utc)
                    failed_run.duration_ms = int((time.perf_counter() - started) * 1000)
                    await session.commit()
                await log_operation("sync", "failed", str(exc), level="ERROR")
                raise


def _apply_folder(row: Folder, item: ScannedFolder, indexed_at: datetime) -> None:
    row.name = item.name
    row.path = item.path
    row.parent_id = item.parent_id
    row.content_type = item.content_type
    row.root_mapping_id = item.root_mapping_id
    row.depth = item.depth
    row.child_folder_count = item.child_folder_count
    row.resource_count = item.resource_count
    row.modified_at = item.modified_at
    row.indexed_at = indexed_at
    row.status = "active"


def _apply_resource(row: Resource, item: ScannedResource, indexed_at: datetime) -> None:
    row.name = item.name
    row.path = item.path
    row.parent_id = item.parent_id
    row.content_type = item.content_type
    row.root_mapping_id = item.root_mapping_id
    row.extension = item.extension
    row.mime_type = item.mime_type
    row.size = item.size
    row.modified_at = item.modified_at
    row.thumbnail = item.thumbnail
    row.indexed_at = indexed_at
    row.status = "active"


async def log_operation(module: str, action: str, message: str, level: str = "INFO") -> None:
    async with StateSession() as session:
        session.add(OperationLog(level=level, module=module, action=action, message=message[:2000]))
        await session.commit()
