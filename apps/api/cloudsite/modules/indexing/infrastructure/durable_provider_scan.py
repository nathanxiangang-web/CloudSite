"""Durable production scanner for provider-backed indexing roots.

This module keeps network directory listing concurrent while serializing the
state.db checkpoint transaction through one AsyncSession. Every directory
claim and completed checkpoint is committed independently so a process crash
can resume from the last durable boundary without rescanning completed dirs.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections import deque
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from cloudsite.alist import AListError
from cloudsite.modules.indexing.domain.snapshot import SnapshotEntry
from cloudsite.modules.providers.contracts.public import ProviderScanRoot

from .durable_scan_checkpoint import DirCheckpoint, ScanRunManager
from .durable_scan_repository import DurableScanRepository

logger = logging.getLogger(__name__)


def _fingerprint(root: ProviderScanRoot, root_path: str) -> str:
    payload = (
        f"{root.root_mapping_id}:{root_path}:{root.content_type}"
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _decode_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return dict(value) if isinstance(value, dict) else {}


def _restore_entry(row: Any, root: ProviderScanRoot) -> SnapshotEntry:
    from .alist_adapter import _stable_id

    path = str(row.path or row.dir_path)
    metadata = _decode_metadata(row.metadata_json)
    metadata["is_dir"] = bool(row.is_dir)
    metadata.setdefault("content_type", root.content_type)
    metadata.setdefault("root_mapping_id", root.root_mapping_id)
    metadata.setdefault("depth", max(path.count("/"), 0))

    parent_path = row.parent_path or metadata.get("parent_path")
    metadata["parent_path"] = parent_path
    if parent_path:
        metadata.setdefault(
            "parent_id",
            _stable_id("folder", str(parent_path), root.root_mapping_id),
        )
    else:
        metadata.setdefault("parent_id", None)

    metadata.setdefault("child_folder_count", 0)
    metadata.setdefault("resource_count", 0)
    metadata.setdefault("extension", "")
    metadata.setdefault("mime_type", "")
    metadata.setdefault("thumbnail", "")

    modified = row.modified
    if isinstance(modified, str):
        modified = datetime.fromisoformat(modified.replace("Z", "+00:00"))

    return SnapshotEntry(
        resource_id=row.resource_id,
        path=path,
        name=row.name,
        size=row.size,
        modified_at=modified,
        content_hash=row.content_hash or row.metadata_hash,
        metadata=metadata,
    )


def _rebuild_folder_counts(entries: list[SnapshotEntry]) -> None:
    folders = {
        entry.path: entry
        for entry in entries
        if bool((entry.metadata or {}).get("is_dir"))
    }
    for folder in folders.values():
        folder.metadata["child_folder_count"] = 0
        folder.metadata["resource_count"] = 0

    for entry in entries:
        parent_path = (entry.metadata or {}).get("parent_path")
        parent = folders.get(str(parent_path)) if parent_path else None
        if parent is None or parent.resource_id == entry.resource_id:
            continue
        if bool((entry.metadata or {}).get("is_dir")):
            parent.metadata["child_folder_count"] += 1
        else:
            parent.metadata["resource_count"] += 1


async def scan_category_durable(
    adapter: Any,
    root: ProviderScanRoot,
    session: AsyncSession,
    *,
    on_progress: Any = None,
    concurrency: int,
) -> tuple[list[SnapshotEntry], str | None, bool]:
    """Scan one root using durable directory checkpoints.

    A resumable running scan is reused only when its fingerprint matches.
    Provider/list failures terminate the run as failed and return a partial
    snapshot; process interruption leaves the run active so the next attempt
    can recover directories that were claimed but not checkpointed.
    """
    from .alist_adapter import (
        DIRECTORY_CONCURRENCY,
        _join_path,
        _normalize_path,
        _parse_time,
        _should_ignore,
        _stable_id,
    )

    repo = DurableScanRepository(session)
    manager = ScanRunManager(session)
    checkpoint = DirCheckpoint(session)

    root_path = _normalize_path(root.storage_path)
    fingerprint = _fingerprint(root, root_path)
    run_id: str | None = None

    active = await repo.get_active_scan_run(root.root_mapping_id)
    if active is not None:
        resume = await checkpoint.resume_scan(active.id, fingerprint)
        if resume.resumed:
            run_id = active.id
            await checkpoint.recover_interrupted(run_id)
            await session.commit()
        else:
            if not str(resume.reason or "").startswith("run_expired"):
                await manager.cancel_scan(active.id)
            await session.commit()

    if run_id is None:
        run = await manager.start_scan(
            root.root_mapping_id,
            fingerprint=fingerprint,
        )
        run_id = run.id
        await repo.add_dirs(run_id, [(root_path, 0)])
        await session.commit()

    staged_rows = await repo.list_entries(run_id)
    entries_by_id: dict[str, SnapshotEntry] = {
        row.resource_id: _restore_entry(row, root)
        for row in staged_rows
    }

    root_id = _stable_id("folder", root_path, root.root_mapping_id)
    root_entry = entries_by_id.get(root_id)
    if root_entry is None:
        root_entry = adapter._make_entry(
            resource_id=root_id,
            path=root_path,
            name=PurePosixPath(root_path).name or root.display_name,
            is_dir=True,
            modified=None,
            root=root,
            parent_path=None,
            depth=0,
        )
        entries_by_id[root_id] = root_entry

    folders_by_path: dict[str, SnapshotEntry] = {
        entry.path: entry
        for entry in entries_by_id.values()
        if bool((entry.metadata or {}).get("is_dir"))
    }
    folders_by_path[root_path] = root_entry

    all_dirs = await repo.list_dirs(run_id)
    scheduled_paths = {row.path for row in all_dirs}
    pending_dirs = [row for row in all_dirs if row.status == "pending"]

    max_workers = max(1, min(concurrency, DIRECTORY_CONCURRENCY))
    queue: asyncio.Queue[tuple[str, int] | None] = asyncio.Queue()
    sentinel: tuple[str, int] | None = None
    for row in pending_dirs:
        await queue.put((row.path, row.depth))

    state: dict[str, int] = {
        "work_remaining": len(pending_dirs),
        "active_workers": 0,
        "dirs_done": sum(1 for row in all_dirs if row.status == "done"),
    }
    recent_paths: deque[str] = deque(maxlen=max_workers)
    pagination_complete = not any(
        row.status == "failed" for row in all_dirs
    )
    db_lock = asyncio.Lock()

    def refresh_metrics() -> None:
        adapter.last_scan_metrics = {
            "active_workers": state["active_workers"],
            "dirs_done": state["dirs_done"],
            "dirs_pending": max(
                state["work_remaining"] - state["active_workers"],
                0,
            ),
            "entries_discovered": len(entries_by_id),
        }

    async def publish_progress() -> None:
        refresh_metrics()
        if on_progress:
            await on_progress(list(recent_paths), len(entries_by_id))

    if state["work_remaining"] == 0:
        failed = await repo.count_dirs(run_id, "failed")
        if failed:
            pagination_complete = False
            await manager.fail_scan(
                run_id,
                f"{failed} durable scan directories failed",
            )
            await session.commit()
        else:
            await manager.complete_scan(run_id)
            await session.commit()

        entries = list(entries_by_id.values())
        _rebuild_folder_counts(entries)
        entries.sort(
            key=lambda entry: (
                int((entry.metadata or {}).get("depth", 0)),
                entry.path,
            )
        )
        refresh_metrics()
        return entries, None, pagination_complete

    async def worker() -> None:
        nonlocal pagination_complete

        while True:
            work = await queue.get()
            if work is sentinel:
                return

            current_path, current_depth = work
            state["active_workers"] += 1
            recent_paths.append(current_path)
            await publish_progress()

            async with db_lock:
                claimed = await repo.claim_dir(run_id, current_path)
                await session.commit()

            if claimed is None:
                state["active_workers"] -= 1
                state["work_remaining"] -= 1
                state["dirs_done"] += 1
                await publish_progress()
                if state["work_remaining"] == 0:
                    for _ in range(max_workers):
                        await queue.put(sentinel)
                continue

            parent_entry = folders_by_path.get(current_path)
            if parent_entry is None:
                parent_entry = adapter._make_entry(
                    resource_id=_stable_id(
                        "folder",
                        current_path,
                        root.root_mapping_id,
                    ),
                    path=current_path,
                    name=PurePosixPath(current_path).name or current_path,
                    is_dir=True,
                    modified=None,
                    root=root,
                    parent_path=None,
                    depth=current_depth,
                )
                entries_by_id[parent_entry.resource_id] = parent_entry
                folders_by_path[current_path] = parent_entry

            try:
                items = await adapter._provider.list_path(current_path)
            except AListError as exc:
                logger.error(
                    "provider list failed for %s: %s; durable dir marked failed",
                    current_path,
                    exc,
                )
                pagination_complete = False
                async with db_lock:
                    await repo.fail_dir(claimed.id, str(exc))
                    await session.commit()

                state["active_workers"] -= 1
                state["work_remaining"] -= 1
                state["dirs_done"] += 1
                await publish_progress()
                if state["work_remaining"] == 0:
                    for _ in range(max_workers):
                        await queue.put(sentinel)
                continue

            dir_entries: list[SnapshotEntry] = []
            child_dirs: list[tuple[str, int]] = []
            new_children: list[tuple[str, int]] = []

            for item in items:
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                item_path = _join_path(current_path, name)
                if _should_ignore(item_path):
                    continue

                is_dir = bool(item.get("is_dir"))
                modified = _parse_time(
                    item.get("modified") or item.get("updated_at")
                )
                item_depth = current_depth + 1
                kind = "folder" if is_dir else "resource"
                entry = adapter._make_entry(
                    resource_id=_stable_id(
                        kind,
                        item_path,
                        root.root_mapping_id,
                    ),
                    path=item_path,
                    name=name,
                    is_dir=is_dir,
                    modified=modified,
                    root=root,
                    parent_path=current_path,
                    depth=item_depth,
                    item=item,
                )
                entries_by_id[entry.resource_id] = entry
                dir_entries.append(entry)

                if is_dir:
                    folders_by_path[item_path] = entry
                    child = (item_path, item_depth)
                    child_dirs.append(child)
                    if item_path not in scheduled_paths:
                        scheduled_paths.add(item_path)
                        new_children.append(child)

            async with db_lock:
                await checkpoint.checkpoint_dir(
                    run_id,
                    current_path,
                    dir_entries,
                    child_dirs,
                )
                await session.commit()

            for child in new_children:
                await queue.put(child)
                state["work_remaining"] += 1

            state["active_workers"] -= 1
            state["work_remaining"] -= 1
            state["dirs_done"] += 1
            await publish_progress()

            if state["work_remaining"] == 0:
                for _ in range(max_workers):
                    await queue.put(sentinel)

    workers = [
        asyncio.create_task(worker())
        for _ in range(max_workers)
    ]
    try:
        await asyncio.gather(*workers)
    except BaseException:
        # Do not let sibling workers keep using the shared AsyncSession after
        # the scan caller has already unwound. Claimed/checkpointed state was
        # committed before provider I/O, so cancellation remains resumable.
        for task in workers:
            if not task.done():
                task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        raise

    failed = await repo.count_dirs(run_id, "failed")
    pending = await repo.count_dirs(run_id, "pending")
    running = await repo.count_dirs(run_id, "running")
    if failed or pending or running:
        pagination_complete = False
        await manager.fail_scan(
            run_id,
            "durable scan incomplete: "
            f"failed={failed} pending={pending} running={running}",
        )
    else:
        await manager.complete_scan(run_id)
    await session.commit()

    entries = list(entries_by_id.values())
    _rebuild_folder_counts(entries)
    entries.sort(
        key=lambda entry: (
            int((entry.metadata or {}).get("depth", 0)),
            entry.path,
        )
    )
    refresh_metrics()
    return entries, None, pagination_complete


__all__ = ["scan_category_durable"]
