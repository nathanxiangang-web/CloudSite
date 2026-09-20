"""Durable scan repository (V2 doc sections 11-13).

Encapsulates CRUD over the three durable scan-progress tables introduced in
R2 PR01 (index_scan_runs, index_scan_dirs, index_scan_entries) so that
future scan/checkpoint logic can resume scans across process restarts.

All methods accept an AsyncSession and only flush; the caller commits or
rolls back the surrounding transaction.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from cloudsite.models import IndexScanDir, IndexScanEntry, IndexScanRun
from cloudsite.modules.indexing.domain.snapshot import SnapshotEntry

_RUN_TERMINAL_FIELDS = frozenset(
    {"finished_at", "total_dirs", "total_entries", "error_message", "fingerprint"}
)
_DIR_TERMINAL_FIELDS = frozenset({"finished_at", "error_message"})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DurableScanRepository:
    """CRUD wrapper over the durable scan-progress tables.

    The repository does not open or commit transactions; every method
    operates against the supplied AsyncSession and only flushes pending
    changes. Callers control the transaction boundary so that scan logic
    can batch multiple repository calls into one atomic unit of work.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # index_scan_runs
    # ------------------------------------------------------------------
    async def create_scan_run(
        self,
        root_mapping_id: int,
        fingerprint: str | None = None,
    ) -> IndexScanRun:
        run = IndexScanRun(
            id=str(uuid.uuid4()),
            root_mapping_id=root_mapping_id,
            status="pending",
            fingerprint=fingerprint,
        )
        self._session.add(run)
        await self._session.flush()
        await self._session.refresh(run)
        return run

    async def get_scan_run(self, run_id: str) -> IndexScanRun | None:
        return await self._session.get(IndexScanRun, run_id)

    async def update_scan_run_status(
        self,
        run_id: str,
        status: str,
        **fields: Any,
    ) -> None:
        values: dict[str, Any] = {"status": status}
        for key, value in fields.items():
            if key not in _RUN_TERMINAL_FIELDS:
                raise ValueError(
                    f"unsupported scan_run field: {key!r}"
                )
            values[key] = value
        if status in {"completed", "failed", "cancelled", "expired"} and values.get(
            "finished_at"
        ) is None:
            values.setdefault("finished_at", _utcnow())
        stmt = (
            update(IndexScanRun)
            .where(IndexScanRun.id == run_id)
            .values(**values)
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def list_scan_runs(
        self,
        root_mapping_id: int,
        limit: int = 100,
    ) -> list[IndexScanRun]:
        stmt = (
            select(IndexScanRun)
            .where(IndexScanRun.root_mapping_id == root_mapping_id)
            .order_by(IndexScanRun.started_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_active_scan_run(
        self,
        root_mapping_id: int,
    ) -> IndexScanRun | None:
        stmt = (
            select(IndexScanRun)
            .where(
                IndexScanRun.root_mapping_id == root_mapping_id,
                IndexScanRun.status == "running",
            )
            .order_by(IndexScanRun.started_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()

    # ------------------------------------------------------------------
    # index_scan_dirs
    # ------------------------------------------------------------------
    async def add_dirs(
        self,
        run_id: str,
        dirs: list[tuple[str, int]],
    ) -> None:
        if not dirs:
            return
        now = _utcnow()
        objects = [
            IndexScanDir(
                id=str(uuid.uuid4()),
                scan_run_id=run_id,
                path=path,
                depth=depth,
                status="pending",
            )
            for path, depth in dirs
        ]
        self._session.add_all(objects)
        await self._session.flush()

    async def claim_next_dir(self, run_id: str) -> IndexScanDir | None:
        """Atomically claim one pending dir for ``run_id`` and mark it running.

        Implemented as a single ``UPDATE ... WHERE id = (SELECT ... LIMIT 1)
        RETURNING *`` statement so that two concurrent claims cannot pick the
        same row: SQLite serializes the write and the subquery re-evaluates
        under the write lock.
        """
        stmt = text(
            "UPDATE index_scan_dirs "
            "SET status = 'running', started_at = :now "
            "WHERE id = ("
            "  SELECT id FROM index_scan_dirs "
            "  WHERE scan_run_id = :run AND status = 'pending' "
            "  ORDER BY depth, id LIMIT 1"
            ") "
            "RETURNING id, scan_run_id, path, depth, status, "
            "started_at, finished_at, entry_count, error_message"
        )
        result = await self._session.execute(stmt, {"run": run_id, "now": _utcnow()})
        row = result.first()
        if row is None:
            return None
        return IndexScanDir(
            id=row.id,
            scan_run_id=row.scan_run_id,
            path=row.path,
            depth=row.depth,
            status=row.status,
            started_at=row.started_at,
            finished_at=row.finished_at,
            entry_count=row.entry_count,
            error_message=row.error_message,
        )

    async def complete_dir(self, dir_id: str, entry_count: int) -> None:
        stmt = (
            update(IndexScanDir)
            .where(IndexScanDir.id == dir_id)
            .values(
                status="done",
                finished_at=_utcnow(),
                entry_count=entry_count,
            )
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def fail_dir(self, dir_id: str, error_message: str) -> None:
        stmt = (
            update(IndexScanDir)
            .where(IndexScanDir.id == dir_id)
            .values(
                status="failed",
                finished_at=_utcnow(),
                error_message=error_message,
            )
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def count_dirs(
        self,
        run_id: str,
        status: str | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(IndexScanDir).where(
            IndexScanDir.scan_run_id == run_id
        )
        if status is not None:
            stmt = stmt.where(IndexScanDir.status == status)
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    # ------------------------------------------------------------------
    # index_scan_entries
    # ------------------------------------------------------------------
    async def add_entries(
        self,
        run_id: str,
        entries: list[SnapshotEntry],
    ) -> None:
        if not entries:
            return
        objects = [
            IndexScanEntry(
                id=str(uuid.uuid4()),
                scan_run_id=run_id,
                dir_path=entry.path,
                resource_id=entry.resource_id,
                name=entry.name,
                is_dir=False,
                modified=entry.modified_at,
                metadata_hash=entry.content_hash,
            )
            for entry in entries
        ]
        self._session.add_all(objects)
        await self._session.flush()

    async def get_entries(
        self,
        run_id: str,
        dir_path: str,
    ) -> list[IndexScanEntry]:
        stmt = (
            select(IndexScanEntry)
            .where(
                IndexScanEntry.scan_run_id == run_id,
                IndexScanEntry.dir_path == dir_path,
            )
            .order_by(IndexScanEntry.id)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count_entries(self, run_id: str) -> int:
        stmt = select(func.count()).select_from(IndexScanEntry).where(
            IndexScanEntry.scan_run_id == run_id
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one())


__all__ = ["DurableScanRepository"]
