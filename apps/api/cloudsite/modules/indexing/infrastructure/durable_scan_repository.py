"""Durable scan repository (V2 doc sections 11-13).

Encapsulates CRUD over the three durable scan-progress tables introduced in
R2 PR01 (index_scan_runs, index_scan_dirs, index_scan_entries) so that
future scan/checkpoint logic can resume scans across process restarts.

All methods accept an AsyncSession and only flush; the caller commits or
rolls back the surrounding transaction.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cloudsite.modules.indexing.domain.snapshot import SnapshotEntry

_RUN_TERMINAL_FIELDS = frozenset(
    {"finished_at", "total_dirs", "total_entries", "error_message", "fingerprint"}
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _row_to_ns(row, fields):
    return SimpleNamespace(**{f: getattr(row, f) for f in fields})


_RUN_FIELDS = ("id", "root_mapping_id", "status", "started_at", "finished_at",
               "fingerprint", "total_dirs", "total_entries", "error_message")
_DIR_FIELDS = ("id", "scan_run_id", "path", "depth", "status", "started_at",
               "finished_at", "entry_count", "error_message")
_ENTRY_FIELDS = (
    "id",
    "scan_run_id",
    "dir_path",
    "path",
    "parent_path",
    "resource_id",
    "name",
    "is_dir",
    "size",
    "modified",
    "content_hash",
    "metadata_json",
    "metadata_hash",
)


class DurableScanRepository:
    """CRUD wrapper over the durable scan-progress tables."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_scan_run(
        self,
        root_mapping_id: int,
        fingerprint: str | None = None,
    ) -> SimpleNamespace:
        run_id = str(uuid.uuid4())
        await self._session.execute(
            text(
                "INSERT INTO index_scan_runs(id, root_mapping_id, status, fingerprint) "
                "VALUES (:id, :rid, 'pending', :fp)"
            ),
            {"id": run_id, "rid": root_mapping_id, "fp": fingerprint},
        )
        await self._session.flush()
        return await self.get_scan_run(run_id)

    async def get_scan_run(self, run_id: str) -> SimpleNamespace | None:
        result = await self._session.execute(
            text(
                "SELECT id, root_mapping_id, status, started_at, finished_at, "
                "fingerprint, total_dirs, total_entries, error_message "
                "FROM index_scan_runs WHERE id = :id"
            ),
            {"id": run_id},
        )
        row = result.first()
        return _row_to_ns(row, _RUN_FIELDS) if row else None

    async def update_scan_run_status(
        self,
        run_id: str,
        status: str,
        **fields: Any,
    ) -> None:
        values: dict[str, Any] = {"status": status}
        for key, value in fields.items():
            if key not in _RUN_TERMINAL_FIELDS:
                raise ValueError(f"unsupported scan_run field: {key!r}")
            values[key] = value
        if status in {"completed", "failed", "cancelled", "expired"} and values.get(
            "finished_at"
        ) is None:
            values.setdefault("finished_at", _utcnow())
        set_parts = [f"{k} = :{k}" for k in values]
        await self._session.execute(
            text(f"UPDATE index_scan_runs SET {', '.join(set_parts)} WHERE id = :id"),
            {**values, "id": run_id},
        )
        await self._session.flush()

    async def list_scan_runs(
        self,
        root_mapping_id: int,
        limit: int = 100,
    ) -> list[SimpleNamespace]:
        result = await self._session.execute(
            text(
                "SELECT id, root_mapping_id, status, started_at, finished_at, "
                "fingerprint, total_dirs, total_entries, error_message "
                "FROM index_scan_runs WHERE root_mapping_id = :rid "
                "ORDER BY started_at DESC LIMIT :lim"
            ),
            {"rid": root_mapping_id, "lim": limit},
        )
        return [_row_to_ns(r, _RUN_FIELDS) for r in result]

    async def get_active_scan_run(
        self,
        root_mapping_id: int,
    ) -> SimpleNamespace | None:
        result = await self._session.execute(
            text(
                "SELECT id, root_mapping_id, status, started_at, finished_at, "
                "fingerprint, total_dirs, total_entries, error_message "
                "FROM index_scan_runs WHERE root_mapping_id = :rid AND status = 'running' "
                "ORDER BY started_at DESC LIMIT 1"
            ),
            {"rid": root_mapping_id},
        )
        row = result.first()
        return _row_to_ns(row, _RUN_FIELDS) if row else None

    async def list_dirs(
        self,
        run_id: str,
        status: str | None = None,
    ) -> list[SimpleNamespace]:
        """List durable directory rows for one run in breadth-first order."""
        if status is None:
            result = await self._session.execute(
                text(
                    "SELECT id, scan_run_id, path, depth, status, started_at, "
                    "finished_at, entry_count, error_message "
                    "FROM index_scan_dirs WHERE scan_run_id = :rid "
                    "ORDER BY depth, id"
                ),
                {"rid": run_id},
            )
        else:
            result = await self._session.execute(
                text(
                    "SELECT id, scan_run_id, path, depth, status, started_at, "
                    "finished_at, entry_count, error_message "
                    "FROM index_scan_dirs "
                    "WHERE scan_run_id = :rid AND status = :status "
                    "ORDER BY depth, id"
                ),
                {"rid": run_id, "status": status},
            )
        return [_row_to_ns(r, _DIR_FIELDS) for r in result]

    async def claim_dir(
        self,
        run_id: str,
        path: str,
    ) -> SimpleNamespace | None:
        """Atomically claim one specific pending directory for scanning."""
        result = await self._session.execute(
            text(
                "UPDATE index_scan_dirs "
                "SET status = 'running', started_at = :now "
                "WHERE scan_run_id = :run AND path = :path AND status = 'pending' "
                "RETURNING id, scan_run_id, path, depth, status, "
                "started_at, finished_at, entry_count, error_message"
            ),
            {"run": run_id, "path": path, "now": _utcnow()},
        )
        row = result.first()
        await self._session.flush()
        return _row_to_ns(row, _DIR_FIELDS) if row else None

    async def add_dirs(
        self,
        run_id: str,
        dirs: list[tuple[str, int]],
    ) -> None:
        if not dirs:
            return
        for path, depth in dirs:
            await self._session.execute(
                text(
                    "INSERT INTO index_scan_dirs(id, scan_run_id, path, depth, status) "
                    "VALUES (:id, :rid, :path, :depth, 'pending')"
                ),
                {"id": str(uuid.uuid4()), "rid": run_id, "path": path, "depth": depth},
            )
        await self._session.flush()

    async def claim_next_dir(self, run_id: str) -> SimpleNamespace | None:
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
        return _row_to_ns(row, _DIR_FIELDS) if row else None

    async def complete_dir(self, dir_id: str, entry_count: int) -> None:
        await self._session.execute(
            text(
                "UPDATE index_scan_dirs SET status = 'done', finished_at = :now, "
                "entry_count = :ec WHERE id = :id"
            ),
            {"now": _utcnow(), "ec": entry_count, "id": dir_id},
        )
        await self._session.flush()

    async def fail_dir(self, dir_id: str, error_message: str) -> None:
        await self._session.execute(
            text(
                "UPDATE index_scan_dirs SET status = 'failed', finished_at = :now, "
                "error_message = :err WHERE id = :id"
            ),
            {"now": _utcnow(), "err": error_message, "id": dir_id},
        )
        await self._session.flush()

    async def count_dirs(
        self,
        run_id: str,
        status: str | None = None,
    ) -> int:
        if status is not None:
            result = await self._session.execute(
                text(
                    "SELECT COUNT(*) FROM index_scan_dirs "
                    "WHERE scan_run_id = :rid AND status = :status"
                ),
                {"rid": run_id, "status": status},
            )
        else:
            result = await self._session.execute(
                text("SELECT COUNT(*) FROM index_scan_dirs WHERE scan_run_id = :rid"),
                {"rid": run_id},
            )
        return int(result.scalar_one())

    async def add_entries(
        self,
        run_id: str,
        entries: list[SnapshotEntry],
        *,
        dir_path: str | None = None,
    ) -> None:
        """Persist staged entries idempotently for one scan run.

        dir_path is the checkpoint scope (the directory that was listed),
        while entry.path is the resource's real path. Keeping those two
        concepts separate is required for safe directory retry/replacement.
        """
        if not entries:
            return
        for entry in entries:
            metadata = dict(entry.metadata or {})
            checkpoint_dir = str(
                dir_path
                if dir_path is not None
                else metadata.get("parent_path") or entry.path
            )
            parent_path = metadata.get("parent_path")
            if parent_path is None and dir_path is not None:
                parent_path = dir_path
            is_dir = bool(metadata.get("is_dir", False))
            await self._session.execute(
                text(
                    "INSERT INTO index_scan_entries("
                    "id, scan_run_id, dir_path, path, parent_path, resource_id, "
                    "name, is_dir, size, modified, content_hash, metadata_json, "
                    "metadata_hash) "
                    "VALUES (:id, :rid, :dp, :path, :parent_path, :resid, "
                    ":name, :is_dir, :size, :mod, :content_hash, :metadata_json, "
                    ":metadata_hash) "
                    "ON CONFLICT(scan_run_id, resource_id) DO UPDATE SET "
                    "dir_path = excluded.dir_path, "
                    "path = excluded.path, "
                    "parent_path = excluded.parent_path, "
                    "name = excluded.name, "
                    "is_dir = excluded.is_dir, "
                    "size = excluded.size, "
                    "modified = excluded.modified, "
                    "content_hash = excluded.content_hash, "
                    "metadata_json = excluded.metadata_json, "
                    "metadata_hash = excluded.metadata_hash"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "rid": run_id,
                    "dp": checkpoint_dir,
                    "path": entry.path,
                    "parent_path": parent_path,
                    "resid": entry.resource_id,
                    "name": entry.name,
                    "is_dir": 1 if is_dir else 0,
                    "size": entry.size,
                    "mod": entry.modified_at,
                    "content_hash": entry.content_hash,
                    "metadata_json": json.dumps(
                        metadata,
                        ensure_ascii=False,
                        sort_keys=True,
                        default=str,
                    ),
                    "metadata_hash": entry.content_hash,
                },
            )
        await self._session.flush()

    async def get_entries(
        self,
        run_id: str,
        dir_path: str,
    ) -> list[SimpleNamespace]:
        result = await self._session.execute(
            text(
                "SELECT id, scan_run_id, dir_path, path, parent_path, "
                "resource_id, name, is_dir, size, modified, content_hash, "
                "metadata_json, metadata_hash FROM index_scan_entries "
                "WHERE scan_run_id = :rid AND dir_path = :dp ORDER BY id"
            ),
            {"rid": run_id, "dp": dir_path},
        )
        return [_row_to_ns(r, _ENTRY_FIELDS) for r in result]

    async def list_entries(
        self,
        run_id: str,
    ) -> list[SimpleNamespace]:
        """Return all staged entries for a scan run in stable insertion order."""
        result = await self._session.execute(
            text(
                "SELECT id, scan_run_id, dir_path, path, parent_path, "
                "resource_id, name, is_dir, size, modified, content_hash, "
                "metadata_json, metadata_hash FROM index_scan_entries "
                "WHERE scan_run_id = :rid ORDER BY id"
            ),
            {"rid": run_id},
        )
        return [_row_to_ns(r, _ENTRY_FIELDS) for r in result]

    async def count_entries(self, run_id: str) -> int:
        result = await self._session.execute(
            text("SELECT COUNT(*) FROM index_scan_entries WHERE scan_run_id = :rid"),
            {"rid": run_id},
        )
        return int(result.scalar_one())


__all__ = ["DurableScanRepository"]
