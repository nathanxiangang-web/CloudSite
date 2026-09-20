"""Durable scan checkpoint logic (V2 doc sections 14-18).

Implements scan run lifecycle, directory checkpoint transactions, crash
recovery, and resume validation over the durable scan-progress tables
introduced in R2 PR01. Builds on DurableScanRepository (R2 PR02).

All methods accept an AsyncSession and only flush; the caller commits or
rolls back the surrounding transaction so that a checkpoint is a single
atomic unit of work (V2 section 14).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cloudsite.modules.indexing.domain.snapshot import SnapshotEntry
from cloudsite.modules.indexing.infrastructure.durable_scan_repository import (
    DurableScanRepository,
)

RESUME_MAX_AGE: timedelta = timedelta(minutes=60)

_DIR_FIELDS = (
    "id",
    "scan_run_id",
    "path",
    "depth",
    "status",
    "started_at",
    "finished_at",
    "entry_count",
    "error_message",
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_aware(value: datetime | str) -> datetime:
    """Normalize SQLite/driver datetime values to timezone-aware UTC."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _dir_row(row) -> SimpleNamespace:
    return SimpleNamespace(**{field: getattr(row, field) for field in _DIR_FIELDS})


@dataclass(slots=True)
class ResumeResult:
    """Outcome of a resume attempt (V2 sections 16-17).

    ``resumed`` is True only when the run is eligible and the fingerprint
    matches; ``pending_dirs`` lists the directories still to be scanned.
    """

    resumed: bool
    reason: str | None
    run_id: str
    pending_dirs: list[SimpleNamespace]


@dataclass(slots=True)
class CompleteGateResult:
    """Complete Gate outcome (V2 doc sections 18-19).

    ``complete`` is True only when every dir is done and the snapshot
    pagination is complete. ``reason`` identifies which condition failed
    (one of: pending_dirs, running_dirs, failed_dirs,
    pagination_incomplete) or None when complete. ``suppressed_count``
    reports how many dirs are not done when the gate fails, so callers
    can surface the magnitude of the incomplete scan.
    """

    complete: bool
    reason: str | None
    suppressed_count: int


class ScanRunManager:
    """Scan run lifecycle: start / complete / fail / cancel / expire stale."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = DurableScanRepository(session)

    async def start_scan(
        self,
        root_mapping_id: int,
        fingerprint: str | None = None,
    ) -> SimpleNamespace:
        """Create a new run and mark it running immediately."""
        run = await self._repo.create_scan_run(
            root_mapping_id, fingerprint=fingerprint
        )
        await self._repo.update_scan_run_status(run.id, "running")
        refreshed = await self._repo.get_scan_run(run.id)
        if refreshed is None:
            raise RuntimeError(f"scan run disappeared after creation: {run.id}")
        return refreshed

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
        result = await self._session.execute(
            text(
                "UPDATE index_scan_runs "
                "SET status = 'expired', finished_at = :now "
                "WHERE status = 'running' AND started_at < :cutoff"
            ),
            {"now": _utcnow(), "cutoff": cutoff},
        )
        await self._session.flush()
        return max(int(result.rowcount or 0), 0)


class DirCheckpoint:
    """Directory checkpoint transaction, crash recovery, resume, complete gate."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = DurableScanRepository(session)

    async def _get_dir(
        self,
        run_id: str,
        dir_path: str,
    ) -> SimpleNamespace | None:
        result = await self._session.execute(
            text(
                "SELECT id, scan_run_id, path, depth, status, started_at, "
                "finished_at, entry_count, error_message "
                "FROM index_scan_dirs "
                "WHERE scan_run_id = :run AND path = :path LIMIT 1"
            ),
            {"run": run_id, "path": dir_path},
        )
        row = result.first()
        return _dir_row(row) if row is not None else None

    async def checkpoint_dir(
        self,
        run_id: str,
        dir_path: str,
        entries: list[SnapshotEntry],
        child_dirs: list[tuple[str, int]],
    ) -> None:
        """Save entries/children before marking the current directory done.

        The caller owns the surrounding transaction. Re-checkpointing an
        already completed directory is a no-op.
        """
        existing = await self._get_dir(run_id, dir_path)
        if existing is not None and existing.status == "done":
            return

        if entries:
            await self._session.execute(
                text(
                    "DELETE FROM index_scan_entries "
                    "WHERE scan_run_id = :run AND dir_path = :path"
                ),
                {"run": run_id, "path": dir_path},
            )
        await self._repo.add_entries(run_id, entries)

        await self._add_child_dirs(run_id, child_dirs)

        if existing is None:
            await self._repo.add_dirs(
                run_id,
                [(dir_path, max(dir_path.count("/"), 0))],
            )
            existing = await self._get_dir(run_id, dir_path)
            if existing is None:
                raise RuntimeError(
                    f"checkpoint directory disappeared after creation: {dir_path}"
                )

        await self._repo.complete_dir(existing.id, entry_count=len(entries))

    async def _add_child_dirs(
        self,
        run_id: str,
        child_dirs: list[tuple[str, int]],
    ) -> None:
        if not child_dirs:
            return
        paths = [path for path, _ in child_dirs]
        placeholders = ", ".join(
            f":path_{index}" for index in range(len(paths))
        )
        params = {"run": run_id}
        params.update(
            {f"path_{index}": path for index, path in enumerate(paths)}
        )
        result = await self._session.execute(
            text(
                "SELECT path FROM index_scan_dirs "
                f"WHERE scan_run_id = :run AND path IN ({placeholders})"
            ),
            params,
        )
        existing_paths = {row[0] for row in result.all()}
        new_dirs = [
            (path, depth)
            for path, depth in child_dirs
            if path not in existing_paths
        ]
        await self._repo.add_dirs(run_id, new_dirs)

    async def recover_interrupted(self, run_id: str) -> None:
        """Reset stale running dirs to pending (V2 section 15).

        Done dirs are never revisited; failed dirs are left for inspection.
        """
        await self._session.execute(
            text(
                "UPDATE index_scan_dirs "
                "SET status = 'pending', started_at = NULL "
                "WHERE scan_run_id = :run AND status = 'running'"
            ),
            {"run": run_id},
        )
        await self._session.flush()

    async def resume_scan(
        self,
        run_id: str,
        fingerprint: str | None,
    ) -> ResumeResult:
        """Validate fingerprint compatibility and return pending dirs."""
        run = await self._repo.get_scan_run(run_id)
        if run is None:
            return ResumeResult(
                resumed=False,
                reason="run_not_found",
                run_id=run_id,
                pending_dirs=[],
            )
        if run.status == "expired":
            return ResumeResult(
                resumed=False,
                reason="run_expired",
                run_id=run_id,
                pending_dirs=[],
            )
        if (
            run.started_at is not None
            and _ensure_aware(run.started_at) < _utcnow() - RESUME_MAX_AGE
        ):
            await self._repo.update_scan_run_status(run_id, "expired")
            return ResumeResult(
                resumed=False,
                reason="run_expired_max_age",
                run_id=run_id,
                pending_dirs=[],
            )
        if run.fingerprint != fingerprint:
            return ResumeResult(
                resumed=False,
                reason="fingerprint_mismatch",
                run_id=run_id,
                pending_dirs=[],
            )

        result = await self._session.execute(
            text(
                "SELECT id, scan_run_id, path, depth, status, started_at, "
                "finished_at, entry_count, error_message "
                "FROM index_scan_dirs "
                "WHERE scan_run_id = :run AND status = 'pending' "
                "ORDER BY depth, id"
            ),
            {"run": run_id},
        )
        pending = [_dir_row(row) for row in result.all()]
        return ResumeResult(
            resumed=True,
            reason=None,
            run_id=run_id,
            pending_dirs=pending,
        )

    async def is_scan_complete(
        self,
        run_id: str,
        pagination_complete: bool = True,
    ) -> CompleteGateResult:
        """Complete gate (V2 doc sections 18-19).

        Returns a CompleteGateResult that is complete only when:
        - pending dirs == 0
        - running dirs == 0
        - failed dirs == 0
        - pagination_complete is True

        ``pagination_complete`` defaults to True so callers that only need
        the dir-state gate can invoke ``is_scan_complete(run_id)`` and get
        a meaningful result. Callers that also tracked pagination should
        pass the snapshot's ``pagination_complete`` flag.

        ``suppressed_count`` is the number of not-done dirs when the gate
        fails on a dir condition, or 0 when it fails only on pagination.
        """
        pending = await self._repo.count_dirs(run_id, "pending")
        running = await self._repo.count_dirs(run_id, "running")
        failed = await self._repo.count_dirs(run_id, "failed")
        if pending > 0:
            return CompleteGateResult(
                complete=False,
                reason="pending_dirs",
                suppressed_count=pending,
            )
        if running > 0:
            return CompleteGateResult(
                complete=False,
                reason="running_dirs",
                suppressed_count=running,
            )
        if failed > 0:
            return CompleteGateResult(
                complete=False,
                reason="failed_dirs",
                suppressed_count=failed,
            )
        if not pagination_complete:
            return CompleteGateResult(
                complete=False,
                reason="pagination_incomplete",
                suppressed_count=0,
            )
        return CompleteGateResult(
            complete=True,
            reason=None,
            suppressed_count=0,
        )


__all__ = [
    "CompleteGateResult",
    "DirCheckpoint",
    "RESUME_MAX_AGE",
    "ResumeResult",
    "ScanRunManager",
]
