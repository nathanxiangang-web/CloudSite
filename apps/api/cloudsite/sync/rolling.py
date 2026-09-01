import hashlib
import json
import mimetypes
import time
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import case, func, select, update
from sqlalchemy.exc import SQLAlchemyError

from ..config import settings
from ..database import IndexSession, StateSession
from ..identity import IdentityObservation, resolve_resource_identities
from ..indexer import (
    MISSING_CANDIDATE_STATUSES,
    is_access_restriction,
    join_path,
    load_client_and_roots,
    log_operation,
    normalize_path,
    open_sync_circuit,
    parse_time,
    stable_id,
    sync_circuit_status,
    sync_lock,
    times_equal,
)
from ..models import (
    ContentRootMapping,
    Folder,
    FolderScanState,
    Resource,
    ResourceIdentityCandidate,
    SyncChange,
    SyncCycle,
    SyncCycleItem,
    SyncRun,
    SystemSetting,
)
from ..search import rebuild_search_index, set_search_index_dirty
from .governor import SyncRequestGovernor
from .planner import WINDOW_INTERVAL, calculate_window_target, next_cycle_anchor, next_window_due_at


SYNC_ENGINE_VERSION = "1.1"
ACTIVE_CYCLE_STATUSES = {"planned", "running", "partial", "overdue"}
PENDING_ITEM_STATUSES = {"pending", "failed", "carry_over"}


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def _system_values(*keys: str) -> dict[str, str]:
    async with StateSession() as session:
        rows = list(
            (
                await session.scalars(
                    select(SystemSetting).where(SystemSetting.key.in_(keys))
                )
            ).all()
        )
    return {row.key: row.value for row in rows}


async def _set_system_values(values: dict[str, str]) -> None:
    async with StateSession() as session:
        for key, value in values.items():
            row = await session.get(SystemSetting, key)
            if row is None:
                session.add(SystemSetting(key=key, value=value))
            else:
                row.value = value
        await session.commit()


async def rolling_enabled() -> bool:
    try:
        values = await _system_values("sync_engine_version")
    except SQLAlchemyError:
        # Unit-level callers and a genuinely uninitialized instance must stay
        # on the legacy bootstrap path until state.db has been initialized.
        return False
    return values.get("sync_engine_version") == SYNC_ENGINE_VERSION


async def _active_cycle(session) -> SyncCycle | None:
    return await session.scalar(
        select(SyncCycle)
        .where(SyncCycle.status.in_(ACTIVE_CYCLE_STATUSES))
        .order_by(SyncCycle.id.desc())
        .limit(1)
    )


async def _create_cycle(session, anchor_at: datetime, cycle_type: str = "normal") -> SyncCycle | None:
    existing = await _active_cycle(session)
    if existing:
        return existing
    folders = list(
        (
            await session.scalars(
                select(Folder)
                .where(Folder.status == "active")
                .order_by(Folder.depth, Folder.path)
            )
        ).all()
    )
    if not folders:
        return None
    cycle = SyncCycle(
        cycle_type=cycle_type,
        status="planned",
        anchor_at=anchor_at,
        planned_folder_count=len(folders),
    )
    session.add(cycle)
    await session.flush()
    for folder in folders:
        session.add(
            SyncCycleItem(
                cycle_id=cycle.id,
                folder_id=folder.id,
                folder_path=folder.path,
                priority=0,
            )
        )
        if not await session.get(FolderScanState, folder.id):
            session.add(FolderScanState(folder_id=folder.id, path=folder.path))
    await session.commit()
    return cycle


async def migrate_existing_index_to_rolling(now: datetime | None = None) -> bool:
    """Migrate only an already completed v1.0 index; never performs bootstrap."""
    now = now or datetime.now(timezone.utc)
    values = await _system_values(
        "sync_engine_version",
        "instance_initialized_at",
        "initial_index_completed_at",
        "sync_engine_migrated_at",
    )
    if values.get("sync_engine_version") == SYNC_ENGINE_VERSION:
        return True

    async with IndexSession() as session:
        latest_success = await session.scalar(
            select(SyncRun)
            .where(SyncRun.status == "success")
            .order_by(SyncRun.id.desc())
            .limit(1)
        )
        folder_count = int(
            await session.scalar(
                select(func.count()).select_from(Folder).where(Folder.status == "active")
            )
            or 0
        )
        if not latest_success or not latest_success.finished_at or folder_count == 0:
            return False
        cycle = await _create_cycle(session, now, "migration")
        if cycle is None:
            return False

    completed_at = _utc(latest_success.finished_at).isoformat()
    initialized_at = _utc(latest_success.started_at).isoformat()
    await _set_system_values(
        {
            "instance_initialized_at": values.get("instance_initialized_at") or initialized_at,
            "initial_index_completed_at": values.get("initial_index_completed_at") or completed_at,
            "sync_engine_version": SYNC_ENGINE_VERSION,
            "sync_engine_migrated_at": values.get("sync_engine_migrated_at") or now.isoformat(),
        }
    )
    await log_operation(
        "sync",
        "rolling_migrated",
        f"同步器已迁移至 Rolling 1.1；保留现有索引并建立 {folder_count} 个目录的首轮队列",
    )
    return True


async def recover_rolling_state() -> None:
    async with IndexSession() as session:
        await session.execute(
            update(SyncCycleItem)
            .where(SyncCycleItem.status == "running")
            .values(status="pending", error_message="服务重启后恢复为待处理")
        )
        await session.commit()


async def resolve_rolling_mode() -> str:
    values = await _system_values(
        "sync_engine_version", "instance_initialized_at", "initial_index_completed_at"
    )
    if values.get("sync_engine_version") != SYNC_ENGINE_VERSION:
        return "AWAITING_INITIAL_SYNC"
    if not values.get("initial_index_completed_at"):
        return "AWAITING_INITIAL_SYNC"
    async with IndexSession() as session:
        folder_count = int(
            await session.scalar(
                select(func.count()).select_from(Folder).where(Folder.status == "active")
            )
            or 0
        )
    if folder_count == 0:
        return "INDEX_RECOVERY_REQUIRED"
    return "NORMAL"


async def prepare_index_recovery(now: datetime | None = None) -> SyncCycle | None:
    """Seed a lost index from state.db roots without re-entering first install."""
    now = now or datetime.now(timezone.utc)
    if await resolve_rolling_mode() != "INDEX_RECOVERY_REQUIRED":
        return None
    async with StateSession() as state:
        roots = list(
            (
                await state.scalars(
                    select(ContentRootMapping)
                    .where(ContentRootMapping.enabled.is_(True))
                    .order_by(ContentRootMapping.sort_order, ContentRootMapping.id)
                )
            ).all()
        )
    if not roots:
        await log_operation(
            "sync",
            "index_recovery_blocked",
            "index.db 需要恢复，但 state.db 中没有启用的 Content Root；未执行首次安装逻辑",
            level="ERROR",
        )
        return None
    async with IndexSession() as session:
        for root in roots:
            path = normalize_path(root.alist_path)
            folder_id = stable_id("folder", path)
            if not await session.get(Folder, folder_id):
                session.add(
                    Folder(
                        id=folder_id,
                        name=PurePosixPath(path).name or root.display_name,
                        path=path,
                        parent_id=None,
                        content_type=root.content_type,
                        root_mapping_id=root.id,
                        depth=0,
                        status="active",
                    )
                )
        await session.commit()
        # The scheduler wakes every minute.  Backdating by one window makes
        # the first recovery window due on that first stable scheduler tick,
        # without applying the first-install six-hour delay.
        cycle = await _create_cycle(session, now - WINDOW_INTERVAL, "recovery")
    await log_operation(
        "sync",
        "index_recovery_seeded",
        f"已从 state.db 的 {len(roots)} 个 Content Root 建立 INDEX_RECOVERY 队列；首次同步历史保持不变",
        level="WARNING",
    )
    return cycle


def validate_scope_entries(parent_path: str, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(entries, list):
        raise ValueError("AList 目录响应 content 不是列表")
    normalized: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for raw in entries:
        if not isinstance(raw, dict):
            raise ValueError("AList 目录响应包含非对象条目")
        name = str(raw.get("name") or "").strip()
        if not name or name in {".", ".."} or "/" in name or "\\" in name:
            raise ValueError("AList 目录响应包含无效名称")
        path = join_path(parent_path, name)
        if path in seen_paths:
            raise ValueError("AList 目录响应包含重复规范化路径")
        seen_paths.add(path)
        is_dir_raw = raw.get("is_dir")
        if isinstance(is_dir_raw, bool):
            is_dir = is_dir_raw
        elif is_dir_raw in (0, 1, "0", "1"):
            is_dir = str(is_dir_raw) == "1"
        else:
            raise ValueError("AList 目录响应 is_dir 无法解释")
        try:
            size = int(raw.get("size") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("AList 目录响应 size 非法") from exc
        if size < 0:
            raise ValueError("AList 目录响应 size 不能为负数")
        normalized.append(
            {
                "name": name,
                "path": path,
                "is_dir": is_dir,
                "size": size,
                "modified_at": parse_time(raw.get("modified") or raw.get("updated_at")),
                "mime_type": str(raw.get("type") or mimetypes.guess_type(name)[0] or "application/octet-stream"),
                "thumbnail": str(raw.get("thumb") or raw.get("thumbnail") or ""),
            }
        )
    return normalized


def scope_fingerprint(entries: list[dict[str, Any]]) -> str:
    canonical = []
    for item in entries:
        modified = item["modified_at"].isoformat() if item["modified_at"] else ""
        canonical.append(
            f"v1|{item['name']}|{'dir' if item['is_dir'] else 'file'}|{item['size']}|{modified}"
        )
    payload = "\n".join(sorted(canonical)).encode("utf-8")
    return hashlib.blake2s(payload).hexdigest()


def _scope_churn_guard(added: int, missing: int, active_total: int) -> bool:
    minimum = settings.sync_mass_change_min_items
    if missing >= minimum:
        return True
    if added >= minimum and missing >= minimum:
        return True
    return active_total >= minimum and missing / max(1, active_total) > settings.sync_mass_change_ratio


def _observe_missing_in_cycle(row: Folder | Resource, cycle_id: int, now: datetime) -> bool:
    if row.missing_last_observed_cycle_id == cycle_id:
        return False
    was_missing = row.status == "missing"
    row.missing_last_observed_cycle_id = cycle_id
    row.missing_streak = int(row.missing_streak or 0) + 1
    row.missing_candidate_at = row.missing_candidate_at or now
    row.indexed_at = now
    row.status = (
        "missing"
        if row.missing_streak >= max(1, settings.sync_missing_confirm_runs)
        else "suspected_missing"
    )
    return not was_missing and row.status == "missing"


async def _resolve_pending_for_parent(
    session,
    cycle: SyncCycle,
    run: SyncRun,
    source_parent: Folder,
    now: datetime,
) -> dict[str, int]:
    """Finish cross-scope move/copy decisions once the old scope was observed."""
    candidates = list(
        (
            await session.scalars(
                select(ResourceIdentityCandidate).where(
                    ResourceIdentityCandidate.cycle_id == cycle.id,
                    ResourceIdentityCandidate.status == "pending",
                    ResourceIdentityCandidate.matched_resource_id.is_not(None),
                )
            )
        ).all()
    )
    added = updated = 0
    for candidate in candidates:
        source = await session.get(Resource, candidate.matched_resource_id)
        if source is None:
            candidate.status = "cancelled"
            candidate.resolved_at = now
            continue
        if source.parent_id != source_parent.id:
            continue
        target_parent = await session.get(Folder, candidate.observed_parent_id)
        if target_parent is None or target_parent.status != "active":
            continue
        observation = IdentityObservation(
            path=candidate.observed_path,
            name=candidate.observed_name,
            root_mapping_id=candidate.root_mapping_id,
            size=candidate.size,
            modified_at=candidate.modified_at,
            extension=candidate.extension,
            mime_type=candidate.mime_type,
        )
        old_path = source.path
        source_missing_this_cycle = source.missing_last_observed_cycle_id == cycle.id
        async with StateSession() as identity_session:
            resolution = (
                await resolve_resource_identities(
                    identity_session,
                    [observation],
                    visible_paths=(
                        {candidate.observed_path}
                        if source_missing_this_cycle
                        else {source.path, candidate.observed_path}
                    ),
                    cycle_id=cycle.id,
                    allowed_candidate_paths={source.path} if source_missing_this_cycle else set(),
                )
            )[0]
        if source_missing_this_cycle:
            if resolution.resource_id != source.id:
                candidate.status = "ambiguous"
                candidate.matched_resource_id = None
                candidate.candidate_resource_ids_json = json.dumps([source.id, resolution.resource_id])
                continue
            row = source
            row.path = candidate.observed_path
            row.parent_id = target_parent.id
            row.content_type = candidate.content_type
            row.root_mapping_id = candidate.root_mapping_id
            row.name = candidate.observed_name
            row.extension = candidate.extension
            row.mime_type = candidate.mime_type
            row.size = candidate.size
            row.modified_at = candidate.modified_at
            row.thumbnail = candidate.thumbnail
            row.indexed_at = now
            row.status = "active"
            row.missing_streak = 0
            row.missing_candidate_at = None
            row.missing_last_observed_cycle_id = None
            row.last_seen_run_id = run.id
            session.add(
                SyncChange(
                    sync_run_id=run.id,
                    object_type="resource",
                    object_id=row.id,
                    change_type="updated",
                    old_path=old_path,
                    new_path=row.path,
                )
            )
            candidate.status = "resolved_move"
            updated += 1
        else:
            row = Resource(
                id=resolution.resource_id,
                name=candidate.observed_name,
                path=candidate.observed_path,
                parent_id=target_parent.id,
                content_type=candidate.content_type,
                root_mapping_id=candidate.root_mapping_id,
                extension=candidate.extension,
                mime_type=candidate.mime_type,
                size=candidate.size,
                modified_at=candidate.modified_at,
                thumbnail=candidate.thumbnail,
                indexed_at=now,
                status="active",
                last_seen_run_id=run.id,
            )
            session.add(row)
            session.add(
                SyncChange(
                    sync_run_id=run.id,
                    object_type="resource",
                    object_id=row.id,
                    change_type="added",
                    new_path=row.path,
                )
            )
            candidate.status = "resolved_new"
            added += 1
        candidate.resolved_at = now
    return {"added": added, "updated": updated}


async def _commit_scope(
    session,
    cycle: SyncCycle,
    cycle_item: SyncCycleItem,
    run: SyncRun,
    parent: Folder,
    entries: list[dict[str, Any]],
    fingerprint: str,
) -> dict[str, int | bool]:
    existing_folders = list(
        (
            await session.scalars(
                select(Folder).where(
                    Folder.parent_id == parent.id,
                    Folder.status.in_(MISSING_CANDIDATE_STATUSES),
                )
            )
        ).all()
    )
    existing_resources = list(
        (
            await session.scalars(
                select(Resource).where(
                    Resource.parent_id == parent.id,
                    Resource.status.in_(MISSING_CANDIDATE_STATUSES),
                )
            )
        ).all()
    )
    folder_by_path = {row.path: row for row in existing_folders}
    resource_by_path = {row.path: row for row in existing_resources}
    resource_by_id = {row.id: row for row in existing_resources}
    incoming_paths = {entry["path"] for entry in entries}
    added_candidates = sum(
        entry["path"] not in (folder_by_path if entry["is_dir"] else resource_by_path)
        for entry in entries
    )
    missing_folders = [row for row in existing_folders if row.path not in incoming_paths]
    missing_resources = [row for row in existing_resources if row.path not in incoming_paths]
    missing_candidates = len(missing_folders) + len(missing_resources)
    if _scope_churn_guard(
        added_candidates,
        missing_candidates,
        len(existing_folders) + len(existing_resources),
    ):
        return {"added": 0, "updated": 0, "removed": 0, "guarded": True, "new_folders": 0}

    resource_entries = [entry for entry in entries if not entry["is_dir"]]
    if resource_entries:
        observations = [
            IdentityObservation(
                path=entry["path"],
                name=entry["name"],
                root_mapping_id=parent.root_mapping_id,
                size=entry["size"],
                modified_at=entry["modified_at"],
                extension=PurePosixPath(entry["name"]).suffix.lower().lstrip("."),
                mime_type=entry["mime_type"],
            )
            for entry in resource_entries
        ]
        async with StateSession() as identity_session:
            resolutions = await resolve_resource_identities(
                identity_session,
                observations,
                visible_paths={entry["path"] for entry in resource_entries},
                cycle_id=cycle.id,
                allowed_candidate_paths={row.path for row in missing_resources},
                defer_unseen_candidates=True,
            )
        for entry, resolution in zip(resource_entries, resolutions, strict=True):
            entry["resource_id"] = resolution.resource_id
            entry["identity_fingerprint"] = resolution.fingerprint
            entry["identity_match_type"] = resolution.match_type
            if resolution.ambiguous_resource_ids or resolution.match_type == "pending_move_or_copy":
                candidate = await session.scalar(
                    select(ResourceIdentityCandidate).where(
                        ResourceIdentityCandidate.cycle_id == cycle.id,
                        ResourceIdentityCandidate.observed_path == entry["path"],
                    )
                )
                if candidate is None:
                    candidate = ResourceIdentityCandidate(
                        cycle_id=cycle.id,
                        observed_path=entry["path"],
                    )
                    session.add(candidate)
                candidate.observed_name = entry["name"]
                candidate.observed_parent_id = parent.id
                candidate.root_mapping_id = parent.root_mapping_id
                candidate.content_type = parent.content_type
                candidate.matched_resource_id = resolution.resource_id if resolution.match_type == "pending_move_or_copy" else None
                candidate.candidate_resource_ids_json = json.dumps(resolution.ambiguous_resource_ids)
                candidate.match_type = "move_or_copy" if resolution.match_type == "pending_move_or_copy" else "ambiguous_fingerprint"
                candidate.confidence = 0.75 if resolution.match_type == "pending_move_or_copy" else 0.0
                candidate.status = "pending" if resolution.match_type == "pending_move_or_copy" else "ambiguous"
                candidate.size = entry["size"]
                candidate.modified_at = entry["modified_at"]
                candidate.extension = PurePosixPath(entry["name"]).suffix.lower().lstrip(".")
                candidate.mime_type = entry["mime_type"]
                candidate.thumbnail = entry["thumbnail"]
                candidate.fingerprint = resolution.fingerprint
        resolved_resource_ids = {
            entry["resource_id"]
            for entry in resource_entries
            if entry["identity_match_type"] != "pending_move_or_copy"
        }
        missing_resources = [row for row in missing_resources if row.id not in resolved_resource_ids]

    now = datetime.now(timezone.utc)
    added = updated = removed = new_folders = 0
    for entry in entries:
        if entry["is_dir"]:
            row = folder_by_path.get(entry["path"])
            if row is None:
                row = Folder(
                    id=stable_id("folder", entry["path"]),
                    name=entry["name"],
                    path=entry["path"],
                    parent_id=parent.id,
                    content_type=parent.content_type,
                    root_mapping_id=parent.root_mapping_id,
                    depth=parent.depth + 1,
                    modified_at=entry["modified_at"],
                    indexed_at=now,
                    status="active",
                )
                session.add(row)
                session.add(SyncChange(sync_run_id=run.id, object_type="folder", object_id=row.id, change_type="added", new_path=row.path))
                added += 1
                new_folders += 1
            else:
                changed = any(
                    (
                        row.name != entry["name"],
                        row.parent_id != parent.id,
                        row.content_type != parent.content_type,
                        row.root_mapping_id != parent.root_mapping_id,
                        row.depth != parent.depth + 1,
                        not times_equal(row.modified_at, entry["modified_at"]),
                        row.status != "active",
                    )
                )
                if changed:
                    session.add(SyncChange(sync_run_id=run.id, object_type="folder", object_id=row.id, change_type="updated", old_path=row.path, new_path=entry["path"]))
                    updated += 1
                row.name = entry["name"]
                row.parent_id = parent.id
                row.content_type = parent.content_type
                row.root_mapping_id = parent.root_mapping_id
                row.depth = parent.depth + 1
                row.modified_at = entry["modified_at"]
                row.indexed_at = now
                row.status = "active"
                row.missing_streak = 0
                row.missing_candidate_at = None
                row.missing_last_observed_cycle_id = None
            await session.flush()
            queued = await session.scalar(
                select(SyncCycleItem).where(
                    SyncCycleItem.cycle_id == cycle.id,
                    SyncCycleItem.folder_id == row.id,
                )
            )
            if queued is None:
                session.add(
                    SyncCycleItem(
                        cycle_id=cycle.id,
                        folder_id=row.id,
                        folder_path=row.path,
                        priority=100,
                    )
                )
                cycle.planned_folder_count += 1
            scan_state = await session.get(FolderScanState, row.id)
            if scan_state is None:
                session.add(FolderScanState(folder_id=row.id, path=row.path))
        else:
            if entry["identity_match_type"] == "pending_move_or_copy":
                continue
            resource_id = entry["resource_id"]
            row = resource_by_path.get(entry["path"]) or resource_by_id.get(resource_id)
            if row is None:
                row = Resource(id=resource_id)
                session.add(row)
                session.add(SyncChange(sync_run_id=run.id, object_type="resource", object_id=row.id, change_type="added", new_path=entry["path"]))
                added += 1
            else:
                changed = any(
                    (
                        row.name != entry["name"],
                        row.parent_id != parent.id,
                        row.size != entry["size"],
                        not times_equal(row.modified_at, entry["modified_at"]),
                        row.status != "active",
                    )
                )
                if changed:
                    session.add(SyncChange(sync_run_id=run.id, object_type="resource", object_id=row.id, change_type="updated", old_path=row.path, new_path=entry["path"]))
                    updated += 1
            row.name = entry["name"]
            row.path = entry["path"]
            row.parent_id = parent.id
            row.content_type = parent.content_type
            row.root_mapping_id = parent.root_mapping_id
            row.extension = PurePosixPath(entry["name"]).suffix.lower().lstrip(".")
            row.mime_type = entry["mime_type"]
            row.size = entry["size"]
            row.modified_at = entry["modified_at"]
            row.thumbnail = entry["thumbnail"]
            row.indexed_at = now
            row.status = "active"
            row.missing_streak = 0
            row.missing_candidate_at = None
            row.missing_last_observed_cycle_id = None
            row.last_seen_run_id = run.id

    for object_type, rows in (("folder", missing_folders), ("resource", missing_resources)):
        for row in rows:
            if _observe_missing_in_cycle(row, cycle.id, now):
                session.add(SyncChange(sync_run_id=run.id, object_type=object_type, object_id=row.id, change_type="removed", old_path=row.path))
                removed += 1

    pending_result = await _resolve_pending_for_parent(session, cycle, run, parent, now)
    added += pending_result["added"]
    updated += pending_result["updated"]

    parent.child_folder_count = sum(entry["is_dir"] for entry in entries)
    parent.resource_count = sum(not entry["is_dir"] for entry in entries)
    parent.indexed_at = now
    parent.last_seen_run_id = run.id
    scan_state = await session.get(FolderScanState, parent.id)
    if scan_state is None:
        scan_state = FolderScanState(folder_id=parent.id, path=parent.path)
        session.add(scan_state)
    scan_state.path = parent.path
    scan_state.fingerprint = fingerprint
    scan_state.fingerprint_version = 1
    scan_state.last_verified_at = now
    scan_state.last_verified_cycle_id = cycle.id
    business_changed = bool(added or updated or removed)
    scan_state.last_scan_result = "changed" if business_changed else "unchanged"
    if business_changed:
        scan_state.last_changed_at = now
    return {"added": added, "updated": updated, "removed": removed, "guarded": False, "new_folders": new_folders}


async def _mark_unchanged(session, cycle: SyncCycle, item: SyncCycleItem, parent: Folder, fingerprint: str) -> None:
    now = datetime.now(timezone.utc)
    state = await session.get(FolderScanState, parent.id)
    if state is None:
        state = FolderScanState(folder_id=parent.id, path=parent.path)
        session.add(state)
    state.path = parent.path
    state.fingerprint = fingerprint
    state.fingerprint_version = 1
    state.last_verified_at = now
    state.last_verified_cycle_id = cycle.id
    state.last_scan_result = "unchanged"
    parent.indexed_at = now


async def _scan_cycle_item(session, client, cycle: SyncCycle, item: SyncCycleItem, run: SyncRun) -> dict[str, Any]:
    parent = await session.get(Folder, item.folder_id)
    if parent is None or parent.status != "active":
        item.status = "superseded"
        item.error_message = "目录已不存在或不再活跃"
        return {"changed": False, "superseded": True, "added": 0, "updated": 0, "removed": 0}
    raw_entries = await client.list_path(item.folder_path, refresh=False, strict=True)
    entries = validate_scope_entries(item.folder_path, raw_entries)
    fingerprint = scope_fingerprint(entries)
    state = await session.get(FolderScanState, parent.id)
    suspected = int(
        await session.scalar(
            select(func.count()).select_from(Folder).where(
                Folder.parent_id == parent.id, Folder.status == "suspected_missing"
            )
        )
        or 0
    ) + int(
        await session.scalar(
            select(func.count()).select_from(Resource).where(
                Resource.parent_id == parent.id, Resource.status == "suspected_missing"
            )
        )
        or 0
    )
    pending_identity = int(
        await session.scalar(
            select(func.count())
            .select_from(ResourceIdentityCandidate)
            .where(
                ResourceIdentityCandidate.cycle_id == cycle.id,
                ResourceIdentityCandidate.status == "pending",
                ResourceIdentityCandidate.matched_resource_id.in_(
                    select(Resource.id).where(Resource.parent_id == parent.id)
                ),
            )
        )
        or 0
    )
    if state and state.fingerprint == fingerprint and suspected == 0 and pending_identity == 0:
        await _mark_unchanged(session, cycle, item, parent, fingerprint)
        return {"changed": False, "superseded": False, "added": 0, "updated": 0, "removed": 0}
    result = await _commit_scope(session, cycle, item, run, parent, entries, fingerprint)
    if result["guarded"]:
        raise RuntimeError("当前目录触发 suspicious churn，已零写入")
    return {
        "changed": bool(result["added"] or result["updated"] or result["removed"]),
        "superseded": False,
        **result,
    }


async def _ensure_current_cycle(session, now: datetime) -> SyncCycle | None:
    active = await _active_cycle(session)
    if active:
        return active
    latest = await session.scalar(select(SyncCycle).order_by(SyncCycle.id.desc()).limit(1))
    if latest is None:
        return await _create_cycle(session, now, "normal")
    anchor = next_cycle_anchor(_utc(latest.anchor_at))
    if now < anchor:
        return None
    return await _create_cycle(session, anchor, "normal")


async def _run_due_rolling_window(manual: bool = False, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    if not await migrate_existing_index_to_rolling(now):
        return {"status": "awaiting_initial_sync"}
    mode = await resolve_rolling_mode()
    if mode == "INDEX_RECOVERY_REQUIRED":
        cycle = await prepare_index_recovery(now)
        if cycle is None:
            return {"status": "index_recovery_blocked"}
        mode = await resolve_rolling_mode()
    if mode != "NORMAL":
        return {"status": mode.lower()}
    if sync_lock.locked():
        return {"status": "already_running"}
    circuit = await sync_circuit_status()
    if circuit["open"]:
        return {"status": "circuit_open", "retry_at": circuit["until"]}

    async with sync_lock:
        async with IndexSession() as session:
            cycle = await _ensure_current_cycle(session, now)
            if cycle is None:
                return {"status": "cycle_not_due"}
            due_at = next_window_due_at(_utc(cycle.anchor_at), cycle.windows_completed)
            if not manual and now < due_at:
                return {"status": "window_not_due", "next_window_at": due_at.isoformat(), "cycle_id": cycle.id}
            remaining = int(
                await session.scalar(
                    select(func.count()).select_from(SyncCycleItem).where(
                        SyncCycleItem.cycle_id == cycle.id,
                        SyncCycleItem.status.in_(PENDING_ITEM_STATUSES),
                    )
                )
                or 0
            )
            if remaining == 0:
                cycle.status = "success"
                cycle.finished_at = now
                await session.commit()
                return {"status": "cycle_complete", "cycle_id": cycle.id}
            target = calculate_window_target(remaining, cycle.windows_completed, cycle.windows_total)
            status_order = case(
                (SyncCycleItem.status == "carry_over", 0),
                (SyncCycleItem.status == "failed", 1),
                else_=2,
            )
            item_ids = list(
                (
                    await session.scalars(
                        select(SyncCycleItem.id)
                        .where(
                            SyncCycleItem.cycle_id == cycle.id,
                            SyncCycleItem.status.in_(PENDING_ITEM_STATUSES),
                        )
                        .order_by(status_order, SyncCycleItem.priority.desc(), SyncCycleItem.id)
                        .limit(target)
                    )
                ).all()
            )
            window_index = min(cycle.windows_total, cycle.windows_completed + 1)
            run = SyncRun(sync_type="rolling_window", status="running", roots_total=len(item_ids))
            session.add(run)
            cycle.status = "running"
            cycle.started_at = cycle.started_at or now
            await session.commit()
            await session.refresh(run)
            cycle_id = cycle.id
            run_id = run.id
            governor = SyncRequestGovernor(target_count=len(item_ids))
            attempted = success = failed = changed = unchanged = 0
            added = updated_count = removed = 0
            circuit_opened = False
            client, _ = await load_client_and_roots()

            async with client:
                for item_id in item_ids:
                    item = await session.get(SyncCycleItem, item_id)
                    if item is None:
                        continue
                    item.status = "running"
                    item.window_index = window_index
                    item.error_message = ""
                    await session.commit()
                    attempted += 1
                    final_error: Exception | None = None
                    for attempt in range(2):
                        await governor.wait_before_request()
                        request_started = time.monotonic()
                        item.attempts += 1
                        cycle.alist_list_requests += 1
                        try:
                            result = await _scan_cycle_item(session, client, cycle, item, run)
                            governor.observe_response(time.monotonic() - request_started, completed=False)
                            if result.get("superseded"):
                                await session.commit()
                                final_error = None
                                break
                            item.status = "success"
                            item.verified_at = datetime.now(timezone.utc)
                            success += 1
                            if result["changed"]:
                                changed += 1
                                added += int(result["added"])
                                updated_count += int(result["updated"])
                                removed += int(result["removed"])
                            else:
                                unchanged += 1
                            await session.commit()
                            final_error = None
                            break
                        except Exception as exc:
                            await session.rollback()
                            final_error = exc
                            governor.observe_response(time.monotonic() - request_started, completed=False)
                            item = await session.get(SyncCycleItem, item_id)
                            cycle = await session.get(SyncCycle, cycle_id)
                            run = await session.get(SyncRun, run_id)
                            # The rollback also removes the request counters
                            # incremented immediately before the AList call.
                            item.attempts += 1
                            cycle.alist_list_requests += 1
                            await session.commit()
                            if is_access_restriction(exc):
                                await open_sync_circuit(exc)
                                circuit_opened = True
                                break
                            if attempt == 0:
                                continue
                    governor.mark_completed()
                    if final_error is not None:
                        item.status = "pending" if circuit_opened else "failed"
                        item.error_message = str(final_error)[:1000]
                        failed += 1
                        await session.commit()
                    if circuit_opened:
                        break

            if changed:
                await set_search_index_dirty(True)
                folders = list((await session.scalars(select(Folder).where(Folder.status == "active"))).all())
                resources = list((await session.scalars(select(Resource).where(Resource.status == "active"))).all())
                await rebuild_search_index(session, folders, resources)
                cycle.fts_rebuilt_count += 1
            cycle.changed_scope_count += changed
            cycle.unchanged_scope_count += unchanged
            if not circuit_opened:
                cycle.windows_completed = min(cycle.windows_total, cycle.windows_completed + 1)
            completed_total = int(
                await session.scalar(
                    select(func.count()).select_from(SyncCycleItem).where(
                        SyncCycleItem.cycle_id == cycle.id,
                        SyncCycleItem.status == "success",
                    )
                )
                or 0
            )
            remaining_total = int(
                await session.scalar(
                    select(func.count()).select_from(SyncCycleItem).where(
                        SyncCycleItem.cycle_id == cycle.id,
                        SyncCycleItem.status.in_(PENDING_ITEM_STATUSES),
                    )
                )
                or 0
            )
            failed_total = int(
                await session.scalar(
                    select(func.count()).select_from(SyncCycleItem).where(
                        SyncCycleItem.cycle_id == cycle.id,
                        SyncCycleItem.status == "failed",
                    )
                )
                or 0
            )
            cycle.completed_folder_count = completed_total
            cycle.failed_folder_count = failed_total
            cycle.carry_over_count = remaining_total
            if circuit_opened:
                cycle.status = "overdue" if now >= next_cycle_anchor(_utc(cycle.anchor_at)) else "partial"
            elif remaining_total == 0:
                cycle.status = "success"
                cycle.finished_at = datetime.now(timezone.utc)
            elif cycle.windows_completed >= cycle.windows_total:
                cycle.status = "overdue"
            else:
                cycle.status = "partial"
            run.status = "failed" if circuit_opened and success == 0 else ("partial" if failed else "success")
            run.folders_scanned = attempted
            run.resources_scanned = 0
            run.added_count = added
            run.updated_count = updated_count
            run.removed_count = removed
            run.roots_completed = success
            run.roots_failed = failed
            run.finished_at = datetime.now(timezone.utc)
            run.duration_ms = int((time.monotonic() - governor.started_at) * 1000)
            run.error_message = "访问限制已打开熔断" if circuit_opened else ""
            await session.commit()
            if changed:
                await set_search_index_dirty(False)

    await log_operation(
        "sync",
        "rolling_window_completed" if not circuit_opened else "rolling_window_interrupted",
        f"Rolling Cycle #{cycle.id} Window {window_index}/{cycle.windows_total}：目标 {target}，成功 {success}，失败 {failed}，变化 {changed}，无变化 {unchanged}",
        level="WARNING" if failed or circuit_opened else "INFO",
    )
    return {
        "status": run.status,
        "cycle_id": cycle.id,
        "window_index": window_index,
        "target": target,
        "attempted": attempted,
        "success": success,
        "failed": failed,
        "changed": changed,
        "unchanged": unchanged,
        "list_requests": governor.request_count,
        "budget_wait_ms": int(governor.budget_wait_seconds * 1000),
        "next_window_at": next_window_due_at(_utc(cycle.anchor_at), cycle.windows_completed).isoformat()
        if cycle.status != "success"
        else None,
    }


async def _finalize_failed_rolling_window(exc: Exception) -> None:
    finished_at = datetime.now(timezone.utc)
    error_message = f"{type(exc).__name__}: {str(exc)}"[:1000]
    async with IndexSession() as session:
        await session.execute(
            update(SyncCycleItem)
            .where(SyncCycleItem.status == "running")
            .values(status="pending", error_message="Rolling 窗口异常中断，已恢复为待处理")
        )
        await session.execute(
            update(SyncRun)
            .where(SyncRun.sync_type == "rolling_window", SyncRun.status == "running")
            .values(status="failed", finished_at=finished_at, error_message=error_message)
        )
        await session.execute(
            update(SyncCycle)
            .where(SyncCycle.status == "running")
            .values(status="partial")
        )
        await session.commit()
    await log_operation(
        "sync",
        "rolling_window_failed",
        f"Rolling 窗口异常中断，运行状态已收尾：{error_message}",
        level="ERROR",
    )


async def run_due_rolling_window(manual: bool = False, now: datetime | None = None) -> dict[str, Any]:
    try:
        return await _run_due_rolling_window(manual=manual, now=now)
    except Exception as exc:
        await _finalize_failed_rolling_window(exc)
        return {"status": "failed", "error": f"{type(exc).__name__}: {str(exc)}"[:1000]}


async def rolling_status() -> dict[str, Any]:
    values = await _system_values("sync_engine_version", "sync_engine_migrated_at", "initial_index_completed_at")
    mode = await resolve_rolling_mode()
    async with IndexSession() as session:
        cycle = await session.scalar(select(SyncCycle).order_by(SyncCycle.id.desc()).limit(1))
        if cycle is None:
            return {"engine_version": values.get("sync_engine_version", "1.0"), "mode": mode, "cycle": None}
        remaining = int(
            await session.scalar(
                select(func.count()).select_from(SyncCycleItem).where(
                    SyncCycleItem.cycle_id == cycle.id,
                    SyncCycleItem.status.in_(PENDING_ITEM_STATUSES),
                )
            )
            or 0
        )
        target = calculate_window_target(remaining, cycle.windows_completed, cycle.windows_total)
        return {
            "engine_version": values.get("sync_engine_version", "1.0"),
            "mode": mode,
            "migrated_at": values.get("sync_engine_migrated_at"),
            "initial_index_completed_at": values.get("initial_index_completed_at"),
            "cycle": {
                "id": cycle.id,
                "type": cycle.cycle_type,
                "status": cycle.status,
                "anchor_at": cycle.anchor_at,
                "windows_total": cycle.windows_total,
                "windows_completed": cycle.windows_completed,
                "next_window_at": next_window_due_at(_utc(cycle.anchor_at), cycle.windows_completed),
                "planned_folder_count": cycle.planned_folder_count,
                "completed_folder_count": cycle.completed_folder_count,
                "failed_folder_count": cycle.failed_folder_count,
                "remaining_folder_count": remaining,
                "next_window_target": target,
                "alist_list_requests": cycle.alist_list_requests,
                "changed_scope_count": cycle.changed_scope_count,
                "unchanged_scope_count": cycle.unchanged_scope_count,
            },
        }
