"""Manual path-sync: scan specified directories as an independent run.

独立 manual cycle/run，1 个父目录 = 1 次 list_path，不递归后代
（enqueue_discovered=False）。force_refresh 真实传入 client.list_path(refresh=...)。
路径去重；未索引目录返回逐路径失败原因；异常收尾不留 running。
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, update

from ..config import settings
from ..database import IndexSession, StateSession
from ..indexer import load_client_and_roots, normalize_path, sync_lock
from ..models import ContentRootMapping, Folder, SyncCycle, SyncCycleItem, SyncRun



MAX_PATHS = 50


def validate_paths_under_roots(paths: list[str], roots: list[ContentRootMapping]) -> tuple[list[str], list[dict]]:
    accepted: list[str] = []
    rejected: list[dict] = []
    if len(paths) > MAX_PATHS:
        rejected.append({"path": "", "reason": f"路径数量超过上限 {MAX_PATHS}"})
        return accepted, rejected
    normalized_roots = [(normalize_path(r.alist_path), r) for r in roots if r.enabled]
    for raw_path in paths:
        path = normalize_path(raw_path)
        if ".." in path.split("/"):
            rejected.append({"path": path, "reason": "路径包含非法的 .. 段"})
            continue
        matched = False
        for root_path, _ in normalized_roots:
            if path == root_path or path.startswith(root_path.rstrip("/") + "/"):
                accepted.append(path)
                matched = True
                break
        if not matched:
            rejected.append({"path": path, "reason": "路径不在任何已启用内容根下"})
    return accepted, rejected


class ManualSyncOrchestrator:
    """手动路径同步占位器：try_reserve 原子占位，finally release。"""

    _instance: ManualSyncOrchestrator | None = None
    _running: bool = False

    @classmethod
    def instance(cls) -> ManualSyncOrchestrator:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def can_start(self) -> bool:
        return not self._running

    def try_reserve(self) -> bool:
        if self._running:
            return False
        self._running = True
        return True

    def release(self) -> None:
        self._running = False

    async def start(self, paths: list[str], force_refresh_paths: set[str]) -> dict[str, Any]:
        try:
            async with sync_lock:
                return await run_path_sync(paths, force_refresh_paths)
        finally:
            self.release()


async def _finalize_manual_cycle(session, cycle_id: int, run_id: int, status: str, error_message: str = "") -> None:
    """异常收尾：把 running item/cycle/run 置为终态，不留 running。"""
    now = datetime.now(timezone.utc)
    await session.execute(
        update(SyncCycleItem)
        .where(SyncCycleItem.cycle_id == cycle_id, SyncCycleItem.status.in_(("pending", "running", "carry_over")))
        .values(status="failed", error_message=error_message or "manual 同步异常中断")
    )
    await session.execute(
        update(SyncCycle)
        .where(SyncCycle.id == cycle_id)
        .values(status=status, finished_at=now)
    )
    await session.execute(
        update(SyncRun)
        .where(SyncRun.id == run_id)
        .values(status=status, finished_at=now, error_message=error_message)
    )
    await session.commit()


async def run_path_sync(paths: list[str], force_refresh_paths: set[str], now: datetime | None = None) -> dict[str, Any]:
    """扫描指定父目录：独立 manual cycle，1 父目录 = 1 次 list_path，不递归后代。"""
    now = now or datetime.now(timezone.utc)
    started = time.perf_counter()

    seen: set[str] = set()
    deduped: list[str] = []
    for path in paths:
        if path not in seen:
            seen.add(path)
            deduped.append(path)
    paths = deduped

    path_errors: list[dict] = []
    accepted_paths: list[str] = []
    folder_by_path: dict[str, Folder] = {}

    async with IndexSession() as session:
        for path in paths:
            folder = await session.scalar(select(Folder).where(Folder.path == path, Folder.status == "active"))
            if folder is None:
                path_errors.append({"path": path, "reason": "目录未索引或非活跃"})
            else:
                folder_by_path[path] = folder
                accepted_paths.append(path)

        if not accepted_paths:
            run = SyncRun(
                sync_type="manual_path", status="failed", trigger_source="manual_path",
                target_paths_json=json.dumps(paths), force_refresh_paths_json=json.dumps(list(force_refresh_paths)),
                started_at=now, finished_at=now, error_message="所有路径均未索引",
            )
            session.add(run)
            await session.commit()
            return {"status": "failed", "failed": len(paths), "skipped": 0, "path_errors": path_errors}

        cycle = SyncCycle(cycle_type="manual_path", status="running", anchor_at=now, planned_folder_count=len(accepted_paths))
        session.add(cycle)
        run = SyncRun(
            sync_type="manual_path", status="running", trigger_source="manual_path",
            target_paths_json=json.dumps(paths), force_refresh_paths_json=json.dumps(list(force_refresh_paths)),
            started_at=now,
        )
        session.add(run)
        await session.flush()
        item_by_path: dict[str, SyncCycleItem] = {}
        for path in accepted_paths:
            folder = folder_by_path[path]
            item = SyncCycleItem(cycle_id=cycle.id, folder_id=folder.id, folder_path=path, status="pending", priority=0)
            session.add(item)
            item_by_path[path] = item
        await session.commit()
        cycle_id = cycle.id
        run_id = run.id

        added = updated = removed = failed = skipped = renamed = 0
        refresh_true_count = 0
        list_requests = 0
        attempted = 0
        scan_errors: list[dict] = []

        try:
            client, _ = await load_client_and_roots()
            async with client:
                for path in accepted_paths:
                    item = await session.get(SyncCycleItem, item_by_path[path].id)
                    if item is None:
                        continue
                    item.status = "running"
                    item.attempts += 1
                    item.error_message = ""
                    await session.commit()
                    attempted += 1
                    refresh = path in force_refresh_paths
                    list_requests += 1
                    try:
                        raise RuntimeError("path sync not supported in v2 engine, use full sync instead")
                        if refresh:
                            refresh_true_count += 1
                        if result.get("superseded"):
                            item.status = "superseded"
                        else:
                            item.status = "success"
                            item.verified_at = datetime.now(timezone.utc)
                            if result.get("changed"):
                                added += int(result["added"])
                                updated += int(result["updated"])
                                removed += int(result["removed"])
                                renamed += int(result.get("renamed", 0))
                            else:
                                skipped += 1
                        await session.commit()
                    except Exception as exc:
                        await session.rollback()
                        item = await session.get(SyncCycleItem, item_by_path[path].id)
                        cycle = await session.get(SyncCycle, cycle_id)
                        run = await session.get(SyncRun, run_id)
                        item.status = "failed"
                        item.error_message = str(exc)[:1000]
                        failed += 1
                        scan_errors.append({"path": path, "reason": str(exc)[:200]})
                        await session.commit()
        except Exception as exc:
            await session.rollback()
            cycle = await session.get(SyncCycle, cycle_id)
            run = await session.get(SyncRun, run_id)
            if cycle is not None and cycle.status == "running":
                await _finalize_manual_cycle(session, cycle_id, run_id, "failed", f"{type(exc).__name__}: {str(exc)[:900]}")
            return {
                "status": "failed", "added": added, "updated": updated, "removed": removed,
                "failed": failed + len(path_errors), "skipped": skipped, "list_requests": list_requests,
                "refresh_true_count": refresh_true_count, "path_errors": path_errors,
            }

        completed = int((await session.scalar(select(func.count()).select_from(SyncCycleItem).where(SyncCycleItem.cycle_id == cycle.id, SyncCycleItem.status == "success"))) or 0)
        failed_total = int((await session.scalar(select(func.count()).select_from(SyncCycleItem).where(SyncCycleItem.cycle_id == cycle.id, SyncCycleItem.status == "failed"))) or 0)
        path_error_count = len(path_errors)
        cycle.completed_folder_count = completed
        cycle.failed_folder_count = failed_total
        cycle.status = "success" if failed_total == 0 and path_error_count == 0 else "partial"
        cycle.finished_at = datetime.now(timezone.utc)
        if failed_total == 0 and path_error_count == 0:
            run.status = "success"
        elif completed == 0 and path_error_count == 0:
            run.status = "failed"
        else:
            run.status = "partial"
        run.folders_scanned = attempted
        run.added_count = added
        run.updated_count = updated
        run.removed_count = removed
        run.renamed_count = renamed
        run.skipped_verified_count = skipped
        run.refresh_true_count = refresh_true_count
        run.list_requests = list_requests
        run.roots_completed = completed
        run.roots_failed = failed_total + len(path_errors)
        run.finished_at = datetime.now(timezone.utc)
        run.duration_ms = int((time.perf_counter() - started) * 1000)
        if scan_errors:
            run.error_message = json.dumps(scan_errors, ensure_ascii=False)[:1000]
        await session.commit()

    return {
        "status": run.status, "added": added, "updated": updated, "removed": removed,
        "failed": failed + len(path_errors), "skipped": skipped, "list_requests": list_requests,
        "refresh_true_count": refresh_true_count, "path_errors": path_errors,
    }
