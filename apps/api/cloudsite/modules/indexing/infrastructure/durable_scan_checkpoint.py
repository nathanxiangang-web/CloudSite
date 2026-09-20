"""Durable scan checkpoint logic (V2 doc sections 14-18).

Implements scan run lifecycle, directory checkpoint transactions, crash
recovery, and resume validation over the durable scan-progress tables
introduced in R2 PR01. Builds on DurableScanRepository (R2 PR02).

All methods accept an AsyncSession and only flush; the caller commits or
rolls back the surrounding transaction so that a checkpoint is a single
atomic unit of work (V2 section 14).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from cloudsite.models import IndexScanDir, IndexScanRun
from cloudsite.modules.indexing.domain.snapshot import SnapshotEntry
from cloudsite.modules.indexing.infrastructure.durable_scan_repository import (
    DurableScanRepository,
)

RESUME_MAX_AGE: timedelta = timedelta(minutes=60)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_aware(dt: datetime) -> datetime:
    """SQLite may return offset-naive datetimes; assume UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


@dataclass(slots=True)
class ResumeResult:
    """Outcome of a resume attempt (V2 sections 16-17).

    ``resumed`` is True only when the run is eligible and the fingerprint
    matches; ``pending_dirs`` lists the directories still to be scanned.
    """

    resumed: bool
    reason: str | None
    run_id: str
    pending_dirs: list[IndexScanDir]


class ScanRunManager:
    """Scan run lifecycle: start / complete / fail / cancel / expire stale."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = DurableScanRepository(session)

    async def start_scan(
        self,
        root_mapping_id: int,
        fingerprint: str | None = None,
    ) -> IndexScanRun:
        """Create a new run and mark it running immediately."""
        run = await self._repo.create_scan_run(
            root_mapping_id, fingerprint=fingerprint
        )
        await self._repo.update_scan_run_status(run.id, "running")
        await self._session.refresh(run)
        return run

    async def complete_scan(self, run_id: str) -> None:
        await self._repo.update_scan_run_status(run_id, "completed")

    async def fail_scan(self, run_id: str, error: str) -> None:
        await self._repo.update_scan_run_status(
            run_id, "failed", error_message=error
        )

    async def cancel_scan(self, run_id: str) -> None:
        await self._repo.update_scan_run_status(run_id, "cancelled")

    async def expire_stale_runs(
        self,
        max_age: timedelta = RESUME_MAX_AGE,
    ) -> int:
        """Mark running runs older than ``max_age`` as expired; return count."""
        cutoff = _utcnow() - max_age
        stmt = select(IndexScanRun.id).where(
            IndexScanRun.status == "running",
            IndexScanRun.started_at < cutoff,
        )
        result = await self._session.execute(stmt)
        stale_ids = [row[0] for row in result.all()]
        if not stale_ids:
            return 0
        now = _utcnow()
        upd = (
            update(IndexScanRun)
            .where(IndexScanRun.id.in_(stale_ids))
            .values(status="expired", finished_at=now)
        )
        await self._session.execute(upd)
        await self._session.flush()
        return len(stale_ids)


class DirCheckpoint:
    """Directory checkpoint transaction, crash recovery, resume, complete gate."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = DurableScanRepository(session)

    async def _get_dir(self, run_id: str, dir_path: str) -> IndexScanDir | None:
        stmt = (
            select(IndexScanDir)
            .where(
                IndexScanDir.scan_run_id == run_id,
                IndexScanDir.path == dir_path,
            )
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def checkpoint_dir(
        self,
        run_id: str,
        dir_path: str,
        entries: list[SnapshotEntry],
        child_dirs: list[tuple[str, int]],
    ) -> None:
        """Single transaction: upsert entries + insert child_dirs as pending + mark dir done.

        Hard rule (V2 section 14): save entries and discovered child dirs
        BEFORE marking the current dir done, so a crash never leaves a done
        dir without its children. Idempotent: re-checkpointing an already
        done dir is a no-op.
        """
        existing = await self._get_dir(run_id, dir_path)
        if existing is not None and existing.status == "done":
            return
        # 1. upsert entries (delete-then-insert for this dir)
        if entries:
            await self._session.execute(
                text(
                    "DELETE FROM index_scan_entries "
                    "WHERE scan_run_id = :run AND dir_path = :path"
                ),
                {"run": run_id, "path": dir_path},
            )
        await self._repo.add_entries(run_id, entries)
        # 2. insert child_dirs as pending, skipping paths already present
        await self._add_child_dirs(run_id, child_dirs)
        # 3. mark the dir done LAST (V2 section 14 hard rule)
        if existing is not None:
            await self._repo.complete_dir(existing.id, entry_count=len(entries))
        else:
            new_dir = IndexScanDir(
                id=str(uuid.uuid4()),
                scan_run_id=run_id,
                path=dir_path,
                depth=max(dir_path.count("/"), 0),
                status="done",
                finished_at=_utcnow(),
                entry_count=len(entries),
            )
            self._session.add(new_dir)
            await self._session.flush()

    async def _add_child_dirs(
        self,
        run_id: str,
        child_dirs: list[tuple[str, int]],
    ) -> None:
        if not child_dirs:
            return
        paths = [p for p, _ in child_dirs]
        stmt = select(IndexScanDir.path).where(
            IndexScanDir.scan_run_id == run_id,
            IndexScanDir.path.in_(paths),
        )
        result = await self._session.execute(stmt)
        existing_paths = {row[0] for row in result.all()}
        new_dirs = [(p, d) for p, d in child_dirs if p not in existing_paths]
        await self._repo.add_dirs(run_id, new_dirs)

    async def recover_interrupted(self, run_id: str) -> None:
        """Reset stale running dirs to pending (V2 section 15).

        Done dirs are never revisited; failed dirs are left for inspection.
        """
        stmt = (
            update(IndexScanDir)
            .where(
                IndexScanDir.scan_run_id == run_id,
                IndexScanDir.status == "running",
            )
            .values(status="pending", started_at=None)
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def resume_scan(
        self,
        run_id: str,
        fingerprint: str | None,
    ) -> ResumeResult:
        """Validate fingerprint compatibility and return pending dirs.

        V2 section 16: runs older than ``RESUME_MAX_AGE`` are expired and
        refused. V2 section 17: a fingerprint mismatch refuses resume.
        """
        run = await self._repo.get_scan_run(run_id)
        if run is None:
            return ResumeResult(
                resumed=False, reason="run_not_found",
                run_id=run_id, pending_dirs=[],
            )
        if run.status == "expired":
            return ResumeResult(
                resumed=False, reason="run_expired",
                run_id=run_id, pending_dirs=[],
            )
        if run.started_at is not None and _ensure_aware(run.started_at) < _utcnow() - RESUME_MAX_AGE:
            await self._repo.update_scan_run_status(run_id, "expired")
            return ResumeResult(
                resumed=False, reason="run_expired_max_age",
                run_id=run_id, pending_dirs=[],
            )
        if run.fingerprint != fingerprint:
            return ResumeResult(
                resumed=False, reason="fingerprint_mismatch",
                run_id=run_id, pending_dirs=[],
            )
        stmt = (
            select(IndexScanDir)
            .where(
                IndexScanDir.scan_run_id == run_id,
                IndexScanDir.status == "pending",
            )
            .order_by(IndexScanDir.id)
        )
        result = await self._session.execute(stmt)
        pending = list(result.scalars().all())
        return ResumeResult(
            resumed=True, reason=None,
            run_id=run_id, pending_dirs=pending,
        )

    async def is_scan_complete(self, run_id: str) -> bool:
        """Complete gate (V2 section 18): pending==0 and running==0 and failed==0."""
        pending = await self._repo.count_dirs(run_id, "pending")
        running = await self._repo.count_dirs(run_id, "running")
        failed = await self._repo.count_dirs(run_id, "failed")
        return pending == 0 and running == 0 and failed == 0


__all__ = [
    "DirCheckpoint",
    "RESUME_MAX_AGE",
    "ResumeResult",
    "ScanRunManager",
]
