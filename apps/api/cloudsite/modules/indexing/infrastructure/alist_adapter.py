"""Provider scan adapter for the v2 indexing engine.

The compatibility class name is retained, but the adapter no longer receives
or imports AListClient. It consumes the Providers public scan contract and
translates provider-neutral list/metadata operations into Indexing snapshots.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import mimetypes
import os
import re
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

from ....alist import AListError
from ...providers.contracts.public import ProviderScanPort, ProviderScanRoot
from ..domain.inspection import InspectionRequest, InspectionResult
from ..domain.snapshot import SnapshotEntry
from .provider_adapter import ProviderCapabilities

logger = logging.getLogger(__name__)

DIRECTORY_CONCURRENCY = 8  # per provider directory concurrency


def _durable_scan_enabled() -> bool:
    """Check the CLOUDSITE_DURABLE_SCAN_ENABLED feature flag (default False)."""
    return os.environ.get("CLOUDSITE_DURABLE_SCAN_ENABLED", "").lower() in (
        "1",
        "true",
        "yes",
    )


def _normalize_path(value: str) -> str:
    path = str(value or "").strip().replace("\\", "/")
    path = re.sub(r"/+", "/", f"/{path.lstrip('/')}")
    return path.rstrip("/") or "/"


def _stable_id(kind: str, path: str, root_mapping_id: int) -> str:
    normalized = _normalize_path(path)
    prefix = "f_" if kind == "folder" else "r_"
    digest = hashlib.sha256(
        f"{root_mapping_id}:{kind}:{normalized}".encode("utf-8")
    ).hexdigest()[:32]
    return prefix + digest


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _join_path(parent: str, name: str) -> str:
    return _normalize_path(
        f"{_normalize_path(parent)}/{str(name).strip('/')}"
    )


def _should_ignore(path: str) -> bool:
    return any(
        part == ".cloudsite"
        for part in PurePosixPath(_normalize_path(path)).parts
    )


class AListProviderAdapter:
    """Compatibility-named Indexing adapter over Providers scan contracts."""

    def __init__(
        self,
        provider: ProviderScanPort,
        roots: list[ProviderScanRoot] | tuple[ProviderScanRoot, ...],
    ) -> None:
        self._provider = provider
        self._roots = {
            f"root:{root.root_mapping_id}": root
            for root in roots
        }
        self.last_scan_metrics: dict[str, int] = {
            "active_workers": 0,
            "dirs_done": 0,
            "dirs_pending": 0,
            "entries_discovered": 0,
        }
        self._durable_session: Any = None

    def set_durable_session(self, session: Any) -> None:
        """Set the DB session used for durable scan checkpoint persistence."""
        self._durable_session = session

    @property
    def provider_id(self) -> str:
        # Preserve the historical persistence key; provider identity is not
        # changed as part of the ownership migration.
        return "generic_alist"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_scan=True,
            supports_pagination=False,
            supports_inspect=True,
            supports_recursive_list=True,
        )

    async def scan_category(
        self,
        category_id: str,
        *,
        cursor: str | None = None,
        limit: int | None = None,
        on_progress: Any = None,
        concurrency: int = DIRECTORY_CONCURRENCY,
    ) -> tuple[list[SnapshotEntry], str | None, bool]:
        root = self._roots.get(category_id)
        if root is None:
            self.last_scan_metrics = {
                "active_workers": 0,
                "dirs_done": 0,
                "dirs_pending": 0,
                "entries_discovered": 0,
            }
            return [], None, True

        if _durable_scan_enabled() and self._durable_session is not None:
            return await self._scan_category_durable(
                root,
                self._durable_session,
                on_progress=on_progress,
                concurrency=concurrency,
            )

        entries: list[SnapshotEntry] = []
        root_path = _normalize_path(root.storage_path)
        root_id = _stable_id("folder", root_path, root.root_mapping_id)
        root_entry = self._make_entry(
            resource_id=root_id,
            path=root_path,
            name=PurePosixPath(root_path).name or root.display_name,
            is_dir=True,
            modified=None,
            root=root,
            parent_path=None,
            depth=0,
        )
        entries.append(root_entry)
        folders_by_path: dict[str, SnapshotEntry] = {
            root_path: root_entry,
        }

        max_workers = max(1, min(concurrency, DIRECTORY_CONCURRENCY))
        queue: asyncio.Queue[tuple[str, int] | None] = asyncio.Queue()
        await queue.put((root_path, 0))

        state: dict[str, int] = {
            "work_remaining": 1,
            "active_workers": 0,
            "dirs_done": 0,
        }
        recent_paths: deque[str] = deque(maxlen=max_workers)
        pagination_complete = True
        sentinel: tuple[str, int] | None = None

        async def worker() -> None:
            nonlocal pagination_complete
            while True:
                item = await queue.get()
                if item is sentinel:
                    return
                current_path, current_depth = item
                state["active_workers"] += 1
                recent_paths.append(current_path)
                parent_entry = folders_by_path[current_path]
                try:
                    items = await self._provider.list_path(current_path)
                except AListError as exc:
                    logger.error(
                        "alist list_path failed for %s: %s, marking scan incomplete",
                        current_path, exc,
                    )
                    pagination_complete = False
                    state["active_workers"] -= 1
                    state["dirs_done"] += 1
                    state["work_remaining"] -= 1
                    if state["work_remaining"] == 0:
                        for _ in range(max_workers):
                            await queue.put(sentinel)
                    continue

                if on_progress:
                    await on_progress(list(recent_paths), len(entries))

                for item in items:
                    name = str(item.get("name") or "").strip()
                    if not name:
                        continue
                    item_path = _join_path(current_path, name)
                    if _should_ignore(item_path):
                        continue
                    is_dir = bool(item.get("is_dir"))
                    if is_dir:
                        parent_entry.metadata["child_folder_count"] += 1
                    else:
                        parent_entry.metadata["resource_count"] += 1
                    modified = _parse_time(
                        item.get("modified") or item.get("updated_at")
                    )
                    kind = "folder" if is_dir else "resource"
                    item_depth = current_depth + 1
                    entry = self._make_entry(
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
                    entries.append(entry)
                    if is_dir:
                        folders_by_path[item_path] = entry
                        await queue.put((item_path, item_depth))
                        state["work_remaining"] += 1

                state["active_workers"] -= 1
                state["dirs_done"] += 1
                state["work_remaining"] -= 1
                if state["work_remaining"] == 0:
                    for _ in range(max_workers):
                        await queue.put(sentinel)

        workers = [asyncio.create_task(worker()) for _ in range(max_workers)]
        await asyncio.gather(*workers)

        entries.sort(key=lambda e: (e.metadata["depth"], e.path))

        self.last_scan_metrics = {
            "active_workers": 0,
            "dirs_done": state["dirs_done"],
            "dirs_pending": 0,
            "entries_discovered": len(entries),
        }
        return entries, None, pagination_complete

    async def _scan_category_durable(
        self,
        root: ProviderScanRoot,
        session: Any,
        *,
        on_progress: Any = None,
        concurrency: int = DIRECTORY_CONCURRENCY,
    ) -> tuple[list[SnapshotEntry], str | None, bool]:
        """Durable scan mode with DB-backed checkpointing and resume.

        When a resumable scan_run with matching fingerprint exists, pending
        dirs are loaded into the in-memory queue and done dirs are skipped.
        Each completed dir is checkpointed atomically; AListError marks the
        dir failed without interrupting other workers.
        """
        from sqlalchemy import select

        from cloudsite.models import IndexScanDir, IndexScanEntry

        from .durable_scan_checkpoint import DirCheckpoint, ScanRunManager
        from .durable_scan_repository import DurableScanRepository

        repo = DurableScanRepository(session)
        mgr = ScanRunManager(session)
        ckpt = DirCheckpoint(session)

        root_path = _normalize_path(root.storage_path)
        root_rid = _stable_id("folder", root_path, root.root_mapping_id)
        fingerprint = hashlib.sha256(
            f"{root.root_mapping_id}:{root_path}:{root.content_type}".encode()
        ).hexdigest()

        entries: list[SnapshotEntry] = []
        folders_by_path: dict[str, SnapshotEntry] = {}
        pagination_complete = True

        max_workers = max(1, min(concurrency, DIRECTORY_CONCURRENCY))
        queue: asyncio.Queue[tuple[str, int] | None] = asyncio.Queue()
        sentinel: tuple[str, int] | None = None
        state: dict[str, int] = {
            "work_remaining": 0,
            "active_workers": 0,
            "dirs_done": 0,
        }
        recent_paths: deque[str] = deque(maxlen=max_workers)

        run_id: str | None = None
        active_run = await repo.get_active_scan_run(root.root_mapping_id)
        if active_run is not None:
            resume_result = await ckpt.resume_scan(active_run.id, fingerprint)
            if resume_result.resumed:
                run_id = active_run.id
                await ckpt.recover_interrupted(run_id)
                done_stmt = (
                    select(IndexScanEntry)
                    .where(IndexScanEntry.scan_run_id == run_id)
                    .order_by(IndexScanEntry.id)
                )
                done_result = await session.execute(done_stmt)
                for row in done_result.scalars().all():
                    entry = SnapshotEntry(
                        resource_id=row.resource_id,
                        path=row.dir_path,
                        name=row.name,
                        size=None,
                        modified_at=row.modified,
                        content_hash=row.metadata_hash,
                        metadata={
                            "is_dir": row.is_dir,
                            "content_type": root.content_type,
                            "root_mapping_id": root.root_mapping_id,
                            "depth": max(row.dir_path.count("/"), 0),
                            "child_folder_count": 0,
                            "resource_count": 0,
                            "parent_path": None,
                            "parent_id": None,
                            "extension": "",
                            "mime_type": "",
                            "thumbnail": "",
                        },
                    )
                    entries.append(entry)
                    if row.is_dir:
                        folders_by_path[row.dir_path] = entry
                pending_after_recover = (
                    select(IndexScanDir)
                    .where(
                        IndexScanDir.scan_run_id == run_id,
                        IndexScanDir.status == "pending",
                    )
                    .order_by(IndexScanDir.id)
                )
                pending_after_result = await session.execute(pending_after_recover)
                for d in pending_after_result.scalars().all():
                    await queue.put((d.path, d.depth))
                    state["work_remaining"] += 1

        if run_id is None:
            run = await mgr.start_scan(
                root.root_mapping_id, fingerprint=fingerprint
            )
            run_id = run.id
            await repo.add_dirs(run_id, [(root_path, 0)])

        if root_path not in folders_by_path:
            root_entry = self._make_entry(
                resource_id=root_rid,
                path=root_path,
                name=PurePosixPath(root_path).name or root.display_name,
                is_dir=True,
                modified=None,
                root=root,
                parent_path=None,
                depth=0,
            )
            entries.append(root_entry)
            folders_by_path[root_path] = root_entry

        if state["work_remaining"] == 0:
            pending_stmt = (
                select(IndexScanDir)
                .where(
                    IndexScanDir.scan_run_id == run_id,
                    IndexScanDir.status == "pending",
                )
                .order_by(IndexScanDir.id)
            )
            pending_result = await session.execute(pending_stmt)
            for d in pending_result.scalars().all():
                await queue.put((d.path, d.depth))
                state["work_remaining"] += 1
            if state["work_remaining"] == 0:
                await queue.put((root_path, 0))
                state["work_remaining"] += 1

        db_lock = asyncio.Lock()

        async def worker() -> None:
            nonlocal pagination_complete
            while True:
                item = await queue.get()
                if item is sentinel:
                    return
                current_path, current_depth = item
                state["active_workers"] += 1
                recent_paths.append(current_path)
                parent_entry = folders_by_path.get(current_path)
                if parent_entry is None:
                    parent_entry = self._make_entry(
                        resource_id=_stable_id(
                            "folder", current_path, root.root_mapping_id
                        ),
                        path=current_path,
                        name=PurePosixPath(current_path).name or current_path,
                        is_dir=True,
                        modified=None,
                        root=root,
                        parent_path=None,
                        depth=current_depth,
                    )
                    entries.append(parent_entry)
                    folders_by_path[current_path] = parent_entry
                try:
                    items = await self._provider.list_path(current_path)
                except AListError as exc:
                    logger.error(
                        "alist list_path failed for %s: %s, marking dir failed",
                        current_path,
                        exc,
                    )
                    pagination_complete = False
                    async with db_lock:
                        existing = await ckpt._get_dir(run_id, current_path)
                        if existing is not None:
                            await repo.fail_dir(existing.id, str(exc))
                        else:
                            new_dir = IndexScanDir(
                                id=str(uuid.uuid4()),
                                scan_run_id=run_id,
                                path=current_path,
                                depth=current_depth,
                                status="failed",
                                finished_at=datetime.now(timezone.utc),
                                error_message=str(exc),
                            )
                            session.add(new_dir)
                        await session.flush()
                    state["active_workers"] -= 1
                    state["dirs_done"] += 1
                    state["work_remaining"] -= 1
                    if state["work_remaining"] == 0:
                        for _ in range(max_workers):
                            await queue.put(sentinel)
                    continue

                if on_progress:
                    await on_progress(list(recent_paths), len(entries))

                dir_entries: list[SnapshotEntry] = []
                child_dirs: list[tuple[str, int]] = []

                for item in items:
                    name = str(item.get("name") or "").strip()
                    if not name:
                        continue
                    item_path = _join_path(current_path, name)
                    if _should_ignore(item_path):
                        continue
                    is_dir = bool(item.get("is_dir"))
                    if is_dir:
                        parent_entry.metadata["child_folder_count"] += 1
                    else:
                        parent_entry.metadata["resource_count"] += 1
                    modified = _parse_time(
                        item.get("modified") or item.get("updated_at")
                    )
                    kind = "folder" if is_dir else "resource"
                    item_depth = current_depth + 1
                    entry = self._make_entry(
                        resource_id=_stable_id(
                            kind, item_path, root.root_mapping_id
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
                    entries.append(entry)
                    dir_entries.append(entry)
                    if is_dir:
                        folders_by_path[item_path] = entry
                        child_dirs.append((item_path, item_depth))
                        await queue.put((item_path, item_depth))
                        state["work_remaining"] += 1

                async with db_lock:
                    await ckpt.checkpoint_dir(
                        run_id, current_path, dir_entries, child_dirs
                    )
                    await session.flush()

                state["active_workers"] -= 1
                state["dirs_done"] += 1
                state["work_remaining"] -= 1
                if state["work_remaining"] == 0:
                    for _ in range(max_workers):
                        await queue.put(sentinel)

        workers = [asyncio.create_task(worker()) for _ in range(max_workers)]
        await asyncio.gather(*workers)

        await mgr.complete_scan(run_id)
        await session.flush()

        entries.sort(key=lambda e: (e.metadata["depth"], e.path))

        self.last_scan_metrics = {
            "active_workers": 0,
            "dirs_done": state["dirs_done"],
            "dirs_pending": 0,
            "entries_discovered": len(entries),
        }
        return entries, None, pagination_complete

    async def inspect(self, request: InspectionRequest) -> InspectionResult:
        info = await self._provider.get_metadata(request.path)
        return InspectionResult(
            resource_id=request.resource_id,
            path=request.path,
            name=info.get("name", ""),
            size=info.get("size"),
            modified_at=_parse_time(info.get("modified")),
            metadata=info,
        )

    @staticmethod
    def _make_entry(
        *,
        resource_id: str,
        path: str,
        name: str,
        is_dir: bool,
        modified: datetime | None,
        root: ProviderScanRoot,
        parent_path: str | None,
        depth: int,
        item: dict[str, Any] | None = None,
    ) -> SnapshotEntry:
        item = item or {}
        ext = PurePosixPath(name).suffix.lower().lstrip(".") if not is_dir else ""
        mime = ""
        if not is_dir:
            mime = str(
                item.get("type")
                or mimetypes.guess_type(name)[0]
                or "application/octet-stream"
            )
        return SnapshotEntry(
            resource_id=resource_id,
            path=path,
            name=name,
            size=int(item.get("size") or 0) if not is_dir else None,
            modified_at=modified,
            content_hash=None,
            metadata={
                "is_dir": is_dir,
                "content_type": root.content_type,
                "root_mapping_id": root.root_mapping_id,
                "depth": depth,
                "child_folder_count": 0,
                "resource_count": 0,
                "parent_path": parent_path,
                "parent_id": (
                    _stable_id(
                        "folder",
                        parent_path,
                        root.root_mapping_id,
                    )
                    if parent_path
                    else None
                ),
                "extension": ext,
                "mime_type": mime,
                "thumbnail": str(item.get("thumb") or item.get("thumbnail") or ""),
            },
        )


__all__ = ["AListProviderAdapter"]
