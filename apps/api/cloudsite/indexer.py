import asyncio
import hashlib
import json
import mimetypes
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from typing import Any, Awaitable, Callable

from sqlalchemy import delete, select, update

from .alist import AListClient, AListError
from .config import settings
from .crypto import decrypt_secret
from .database import IndexSession, StateSession
from .identity import IdentityObservation, resolve_resource_identities
from .models import (
    AListConnection,
    ContentRootMapping,
    Folder,
    OperationLog,
    Resource,
    ResourceIdentityCandidate,
    SyncChange,
    SyncRootResult,
    SyncRun,
    SystemSetting,
)
from .search import rebuild_search_index, set_search_index_dirty


sync_lock = asyncio.Lock()
MISSING_CANDIDATE_STATUSES = {"active", "suspected_missing"}


@dataclass(slots=True)
class SyncRateLimiter:
    requests_per_second: float
    jitter_ms: int = 0
    _next_request_at: float = 0.0

    async def wait(self) -> None:
        now = time.monotonic()
        if self._next_request_at > now:
            await asyncio.sleep(self._next_request_at - now)
        interval = 1.0 / max(0.1, self.requests_per_second)
        jitter = random.uniform(0, max(0, self.jitter_ms)) / 1000
        self._next_request_at = time.monotonic() + interval + jitter


def is_access_restriction(exc: Exception) -> bool:
    text = str(exc).lower()
    return isinstance(exc, AListError) and (
        exc.status_code in {405, 429}
        or "405" in text
        or "429" in text
        or "waf" in text
        or "blocked" in text
        or "访问限制" in text
        or "请求过于频繁" in text
    )


def mass_change_guard_triggered(added: int, missing: int, active_total: int) -> bool:
    if missing <= 0:
        return False
    ratio = missing / max(1, active_total)
    symmetric_churn = added >= settings.sync_mass_change_min_items and missing >= settings.sync_mass_change_min_items
    return missing >= settings.sync_mass_change_min_items or ratio > settings.sync_mass_change_ratio or symmetric_churn


def advance_missing_candidate(row: Folder | Resource, now: datetime, confirm_runs: int) -> bool:
    was_missing = row.status == "missing"
    row.missing_streak = int(row.missing_streak or 0) + 1
    row.missing_candidate_at = row.missing_candidate_at or now
    row.indexed_at = now
    if row.missing_streak >= max(1, confirm_runs):
        row.status = "missing"
    else:
        row.status = "suspected_missing"
    return not was_missing and row.status == "missing"


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


async def _set_system_values(values: dict[str, str]) -> None:
    async with StateSession() as session:
        for key, value in values.items():
            row = await session.get(SystemSetting, key)
            if row is None:
                session.add(SystemSetting(key=key, value=value))
            else:
                row.value = value
        await session.commit()


async def sync_circuit_status() -> dict[str, Any]:
    async with StateSession() as session:
        rows = list(
            (
                await session.scalars(
                    select(SystemSetting).where(
                        SystemSetting.key.in_(("sync_circuit_until", "sync_circuit_reason", "sync_circuit_failures"))
                    )
                )
            ).all()
        )
    values = {row.key: row.value for row in rows}
    until = parse_time(values.get("sync_circuit_until"))
    now = datetime.now(timezone.utc)
    return {
        "open": bool(until and until > now),
        "until": until,
        "reason": values.get("sync_circuit_reason", ""),
        "failures": int(values.get("sync_circuit_failures", "0") or 0),
    }


async def open_sync_circuit(exc: Exception) -> datetime:
    current = await sync_circuit_status()
    failures = int(current["failures"]) + 1
    cooldown_minutes = 30 if failures == 1 else 120
    until = datetime.now(timezone.utc) + timedelta(minutes=cooldown_minutes)
    await _set_system_values(
        {
            "sync_circuit_until": until.isoformat(),
            "sync_circuit_reason": "AList / Storage 返回访问限制，已暂停同步以避免继续触发风控",
            "sync_circuit_failures": str(failures),
        }
    )
    return until


async def reset_sync_circuit() -> None:
    await _set_system_values(
        {
            "sync_circuit_until": "",
            "sync_circuit_reason": "",
            "sync_circuit_failures": "0",
        }
    )


async def automatic_sync_due(interval_minutes: int) -> bool:
    now = datetime.now(timezone.utc)
    async with IndexSession() as session:
        latest = await session.scalar(select(SyncRun).order_by(SyncRun.id.desc()).limit(1))
        latest_success = await session.scalar(
            select(SyncRun)
            .where(SyncRun.status == "success")
            .order_by(SyncRun.id.desc())
            .limit(1)
        )
    if latest and latest.status == "running":
        return False
    if latest and latest.status != "success" and latest.finished_at:
        finished_at = latest.finished_at if latest.finished_at.tzinfo else latest.finished_at.replace(tzinfo=timezone.utc)
        if (now - finished_at).total_seconds() < settings.sync_failure_retry_delay_seconds:
            return False
    if not latest_success or not latest_success.finished_at:
        return True
    finished_at = latest_success.finished_at
    finished_at = finished_at if finished_at.tzinfo else finished_at.replace(tzinfo=timezone.utc)
    return now - finished_at >= timedelta(minutes=interval_minutes)


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
    progress: Callable[[int, int, str], Awaitable[None]] | None = None,
    rate_limiter: SyncRateLimiter | None = None,
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
            if rate_limiter:
                await rate_limiter.wait()
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
                await progress(len(folders), len(resources), current_path)

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


async def resolve_scanned_resource_ids(
    session,
    resources: dict[str, ScannedResource],
) -> dict[str, ScannedResource]:
    """Resolve one complete full-scan batch before index rows are written."""
    items = list(resources.values())
    if not items:
        return {}
    observations = [
        IdentityObservation(
            path=item.path,
            name=item.name,
            root_mapping_id=item.root_mapping_id,
            size=item.size,
            modified_at=item.modified_at,
            extension=item.extension,
            mime_type=item.mime_type,
        )
        for item in items
    ]
    async with StateSession() as identity_session:
        resolutions = await resolve_resource_identities(
            identity_session,
            observations,
            visible_paths={item.path for item in items},
        )
    for item, resolution in zip(items, resolutions, strict=True):
        item.id = resolution.resource_id
        if resolution.ambiguous_resource_ids:
            session.add(
                ResourceIdentityCandidate(
                    cycle_id=None,
                    observed_path=item.path,
                    matched_resource_id=None,
                    candidate_resource_ids_json=json.dumps(resolution.ambiguous_resource_ids),
                    match_type="ambiguous_fingerprint",
                    confidence=0.0,
                    status="ambiguous",
                    size=item.size,
                    modified_at=item.modified_at,
                    extension=item.extension,
                    mime_type=item.mime_type,
                    fingerprint=resolution.fingerprint,
                )
            )
    return {item.id: item for item in items}


async def _running_sync_result() -> dict[str, Any]:
    async with IndexSession() as session:
        row = await session.scalar(select(SyncRun).where(SyncRun.status == "running").order_by(SyncRun.id.desc()).limit(1))
    return {"status": "already_running", "run_id": row.id if row else None}


async def _manual_cooldown_result() -> dict[str, Any] | None:
    async with IndexSession() as session:
        row = await session.scalar(
            select(SyncRun).where(SyncRun.status == "success").order_by(SyncRun.id.desc()).limit(1)
        )
    if not row or not row.finished_at:
        return None
    finished_at = row.finished_at if row.finished_at.tzinfo else row.finished_at.replace(tzinfo=timezone.utc)
    remaining = settings.sync_manual_cooldown_seconds - int((datetime.now(timezone.utc) - finished_at).total_seconds())
    if remaining <= 0:
        return None
    return {"status": "cooldown", "run_id": row.id, "retry_after_seconds": remaining}


async def sync_preflight(sync_type: str = "manual", force: bool = False) -> dict[str, Any] | None:
    """Return an immediate reason why a new sync must not start."""
    if sync_lock.locked():
        return await _running_sync_result()
    circuit = await sync_circuit_status()
    if circuit["open"]:
        return {
            "status": "circuit_open",
            "retry_at": circuit["until"].isoformat() if circuit["until"] else None,
            "message": circuit["reason"],
        }
    if sync_type == "manual" and not force:
        return await _manual_cooldown_result()
    return None


async def _commit_root(
    session,
    run: SyncRun,
    root: ContentRootMapping,
    scanned_folders: dict[str, ScannedFolder],
    scanned_resources: dict[str, ScannedResource],
) -> tuple[int, int, int, bool]:
    existing_folders = {
        row.id: row
        for row in (await session.scalars(select(Folder).where(Folder.root_mapping_id == root.id))).all()
    }
    existing_resources = {
        row.id: row
        for row in (await session.scalars(select(Resource).where(Resource.root_mapping_id == root.id))).all()
    }
    scanned_folders, scanned_resources = preserve_existing_ids(
        scanned_folders, scanned_resources, existing_folders, existing_resources
    )
    added_candidates = sum(object_id not in existing_folders for object_id in scanned_folders)
    added_candidates += sum(object_id not in existing_resources for object_id in scanned_resources)
    missing_folders = [
        row
        for object_id, row in existing_folders.items()
        if row.status in MISSING_CANDIDATE_STATUSES and object_id not in scanned_folders
    ]
    missing_resources = [
        row
        for object_id, row in existing_resources.items()
        if row.status in MISSING_CANDIDATE_STATUSES and object_id not in scanned_resources
    ]
    active_total = sum(row.status in MISSING_CANDIDATE_STATUSES for row in existing_folders.values())
    active_total += sum(row.status in MISSING_CANDIDATE_STATUSES for row in existing_resources.values())
    missing_candidates = len(missing_folders) + len(missing_resources)
    guarded = mass_change_guard_triggered(
        added_candidates, missing_candidates, active_total
    )
    added = updated = removed = 0
    now = datetime.now(timezone.utc)

    if guarded:
        session.add(
            SyncRootResult(
                sync_run_id=run.id,
                root_mapping_id=root.id,
                root_path=normalize_path(root.alist_path),
                status="suspicious_churn",
                folders_scanned=len(scanned_folders),
                resources_scanned=len(scanned_resources),
                added_count=added_candidates,
                updated_count=0,
                removed_count=missing_candidates,
                error_message=(
                    "检测到异常大规模路径变化，已对整个内容根执行零写入保护："
                    f"候选新增 {added_candidates}，候选缺失 {missing_candidates}，"
                    f"原活跃对象 {active_total}"
                ),
            )
        )
        await session.commit()
        return 0, 0, 0, True

    scanned_resources = await resolve_scanned_resource_ids(session, scanned_resources)
    missing_resources = [
        row
        for object_id, row in existing_resources.items()
        if row.status in MISSING_CANDIDATE_STATUSES and object_id not in scanned_resources
    ]

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
        _apply_folder(row, item, now, run.id)

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
        _apply_resource(row, item, now, run.id)

    for object_type, rows in (("folder", missing_folders), ("resource", missing_resources)):
        for row in rows:
            if advance_missing_candidate(row, now, settings.sync_missing_confirm_runs):
                session.add(SyncChange(sync_run_id=run.id, object_type=object_type, object_id=row.id, change_type="removed", old_path=row.path))
                removed += 1

    session.add(
        SyncRootResult(
            sync_run_id=run.id,
            root_mapping_id=root.id,
            root_path=normalize_path(root.alist_path),
            status="success",
            folders_scanned=len(scanned_folders),
            resources_scanned=len(scanned_resources),
            added_count=added,
            updated_count=updated,
            removed_count=removed,
            error_message="",
        )
    )
    await session.commit()
    return added, updated, removed, guarded


async def run_sync(sync_type: str = "manual", full: bool = False, force: bool = False) -> dict[str, Any]:
    preflight = await sync_preflight(sync_type, force)
    if preflight:
        return preflight

    async with sync_lock:
        started = time.perf_counter()
        async with IndexSession() as session:
            running = await session.scalar(select(SyncRun.id).where(SyncRun.status == "running").limit(1))
            if running:
                return {"status": "already_running", "run_id": running}
            client, roots = await load_client_and_roots()
            run = SyncRun(
                sync_type="full" if full else sync_type,
                status="running",
                roots_total=len(roots),
            )
            session.add(run)
            await session.commit()
            await session.refresh(run)
            run_id = run.id
            total_folders = total_resources = 0
            added = updated = removed = 0
            completed = failed = 0
            suspicious = False
            errors: list[str] = []
            limiter = SyncRateLimiter(settings.sync_list_rps, settings.sync_list_jitter_ms)

            async with client:
                for root in roots:
                    base_folders, base_resources = total_folders, total_resources
                    last_progress_at = 0.0

                    async def update_progress(folder_count: int, resource_count: int, current_path: str) -> None:
                        nonlocal last_progress_at
                        current = time.monotonic()
                        if current - last_progress_at < 1.0:
                            return
                        await session.execute(
                            update(SyncRun)
                            .where(SyncRun.id == run_id)
                            .values(
                                folders_scanned=base_folders + folder_count,
                                resources_scanned=base_resources + resource_count,
                                current_path=current_path,
                            )
                        )
                        await session.commit()
                        last_progress_at = current

                    try:
                        scanned_folders, scanned_resources = await scan_roots(
                            client, [root], update_progress, limiter
                        )
                        total_folders += len(scanned_folders)
                        total_resources += len(scanned_resources)
                        root_added, root_updated, root_removed, guarded = await _commit_root(
                            session, run, root, scanned_folders, scanned_resources
                        )
                        added += root_added
                        updated += root_updated
                        removed += root_removed
                        suspicious = suspicious or guarded
                        completed += 1
                        run = await session.get(SyncRun, run_id)
                        run.roots_completed = completed
                        run.folders_scanned = total_folders
                        run.resources_scanned = total_resources
                        run.current_path = normalize_path(root.alist_path)
                        await session.commit()
                    except Exception as exc:
                        await session.rollback()
                        failed += 1
                        message = str(exc)[:1000]
                        errors.append(f"{normalize_path(root.alist_path)}: {message}")
                        run = await session.get(SyncRun, run_id)
                        run.roots_failed = failed
                        run.error_message = "\n".join(errors)[:2000]
                        session.add(
                            SyncRootResult(
                                sync_run_id=run_id,
                                root_mapping_id=root.id,
                                root_path=normalize_path(root.alist_path),
                                status="failed",
                                error_message=message,
                            )
                        )
                        await session.commit()
                        if is_access_restriction(exc):
                            await open_sync_circuit(exc)
                            break

            await set_search_index_dirty(True)
            all_folders = list((await session.scalars(select(Folder))).all())
            all_resources = list((await session.scalars(select(Resource))).all())
            await rebuild_search_index(session, all_folders, all_resources)
            run = await session.get(SyncRun, run_id)
            if completed == 0 and failed:
                run.status = "failed"
            elif failed:
                run.status = "partial"
            elif suspicious:
                run.status = "suspicious_churn"
            else:
                run.status = "success"
            now = datetime.now(timezone.utc)
            run.folders_scanned = total_folders
            run.resources_scanned = total_resources
            run.added_count = added
            run.updated_count = updated
            run.removed_count = removed
            run.roots_completed = completed
            run.roots_failed = failed
            run.current_path = ""
            run.finished_at = now
            run.duration_ms = int((time.perf_counter() - started) * 1000)
            await session.commit()
            await set_search_index_dirty(False)
            if run.status == "success":
                await reset_sync_circuit()
            level = "INFO" if run.status == "success" else "WARNING"
            await log_operation(
                "sync",
                run.status,
                f"同步结束：{completed}/{len(roots)} 个根目录完成；{total_folders} 个文件夹，{total_resources} 个资源；新增 {added}，修改 {updated}，移除 {removed}",
                level=level,
            )
            return {
                "id": run.id,
                "status": run.status,
                "folders": total_folders,
                "resources": total_resources,
                "added": added,
                "updated": updated,
                "removed": removed,
                "roots_completed": completed,
                "roots_failed": failed,
                "duration_ms": run.duration_ms,
            }


def _apply_folder(row: Folder, item: ScannedFolder, indexed_at: datetime, run_id: int) -> None:
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
    row.missing_streak = 0
    row.missing_candidate_at = None
    row.last_seen_run_id = run_id


def _apply_resource(row: Resource, item: ScannedResource, indexed_at: datetime, run_id: int) -> None:
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
    row.missing_streak = 0
    row.missing_candidate_at = None
    row.last_seen_run_id = run_id


async def log_operation(module: str, action: str, message: str, level: str = "INFO") -> None:
    async with StateSession() as session:
        session.add(OperationLog(level=level, module=module, action=action, message=message[:2000]))
        await session.commit()
