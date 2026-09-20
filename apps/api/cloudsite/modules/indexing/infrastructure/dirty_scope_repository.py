"""Dirty scope repository (V2 doc section 29).

Encapsulates CRUD over the index_dirty_scopes table introduced in R6 PR01 so
that verification mismatches detected during indexing survive process
restarts and can be reprocessed by a future reconciliation worker.

This repository is intentionally text-based SQL only: it does not import
cloudsite.models. All methods accept an AsyncSession and only flush; the
caller commits or rolls back the surrounding transaction.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class DirtyScopeRecord:
    """Immutable snapshot of one index_dirty_scopes row."""

    id: int
    root_mapping_id: int
    path: str
    reason: str
    priority: int
    status: str
    attempts: int
    detected_at: str
    updated_at: str
    last_error_code: str | None
    last_error_message: str | None


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_record(row) -> DirtyScopeRecord:
    return DirtyScopeRecord(
        id=row.id,
        root_mapping_id=row.root_mapping_id,
        path=row.path,
        reason=row.reason,
        priority=row.priority,
        status=row.status,
        attempts=row.attempts,
        detected_at=row.detected_at,
        updated_at=row.updated_at,
        last_error_code=row.last_error_code,
        last_error_message=row.last_error_message,
    )


_SELECT_COLS = (
    "id, root_mapping_id, path, reason, priority, status, attempts, "
    "detected_at, updated_at, last_error_code, last_error_message"
)


class DirtyScopeRepository:
    """CRUD wrapper over the index_dirty_scopes table.

    Text-based SQL only; does not import cloudsite.models. The caller is
    responsible for committing the surrounding transaction.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self,
        root_mapping_id: int,
        path: str,
        reason: str = "verification_mismatch",
        priority: int = 0,
    ) -> int:
        """Insert a dirty scope row and return its id.

        Raises if (root_mapping_id, path) already exists due to the UNIQUE
        constraint; the caller decides whether to update instead.
        """
        result = await self._session.execute(
            text(
                "INSERT INTO index_dirty_scopes(root_mapping_id, path, reason, priority) "
                "VALUES (:rid, :path, :reason, :priority)"
            ),
            {"rid": root_mapping_id, "path": path, "reason": reason, "priority": priority},
        )
        await self._session.flush()
        return int(result.lastrowid)

    async def get(self, dirty_scope_id: int) -> DirtyScopeRecord | None:
        result = await self._session.execute(
            text(f"SELECT {_SELECT_COLS} FROM index_dirty_scopes WHERE id = :id"),
            {"id": dirty_scope_id},
        )
        row = result.first()
        return _row_to_record(row) if row else None

    async def find_pending(self, root_mapping_id: int) -> list[DirtyScopeRecord]:
        result = await self._session.execute(
            text(
                f"SELECT {_SELECT_COLS} FROM index_dirty_scopes "
                "WHERE root_mapping_id = :rid AND status = 'pending' "
                "ORDER BY priority DESC, id"
            ),
            {"rid": root_mapping_id},
        )
        return [_row_to_record(r) for r in result]

    async def find_by_status(self, status: str) -> list[DirtyScopeRecord]:
        result = await self._session.execute(
            text(
                f"SELECT {_SELECT_COLS} FROM index_dirty_scopes "
                "WHERE status = :status ORDER BY priority DESC, id"
            ),
            {"status": status},
        )
        return [_row_to_record(r) for r in result]

    async def update_status(
        self,
        dirty_scope_id: int,
        status: str,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        if error_code is not None or error_message is not None:
            await self._session.execute(
                text(
                    "UPDATE index_dirty_scopes SET status = :status, "
                    "last_error_code = :ec, last_error_message = :em, "
                    "updated_at = datetime('now') WHERE id = :id"
                ),
                {
                    "status": status,
                    "ec": error_code,
                    "em": error_message,
                    "id": dirty_scope_id,
                },
            )
        else:
            await self._session.execute(
                text(
                    "UPDATE index_dirty_scopes SET status = :status, "
                    "updated_at = datetime('now') WHERE id = :id"
                ),
                {"status": status, "id": dirty_scope_id},
            )
        await self._session.flush()

    async def increment_attempts(self, dirty_scope_id: int) -> None:
        await self._session.execute(
            text(
                "UPDATE index_dirty_scopes SET attempts = attempts + 1, "
                "updated_at = datetime('now') WHERE id = :id"
            ),
            {"id": dirty_scope_id},
        )
        await self._session.flush()

    async def resolve(self, dirty_scope_id: int) -> None:
        await self._session.execute(
            text(
                "UPDATE index_dirty_scopes SET status = 'resolved', "
                "updated_at = datetime('now') WHERE id = :id"
            ),
            {"id": dirty_scope_id},
        )
        await self._session.flush()

    async def delete(self, dirty_scope_id: int) -> None:
        await self._session.execute(
            text("DELETE FROM index_dirty_scopes WHERE id = :id"),
            {"id": dirty_scope_id},
        )
        await self._session.flush()

    async def exists(self, root_mapping_id: int, path: str) -> bool:
        result = await self._session.execute(
            text(
                "SELECT 1 FROM index_dirty_scopes "
                "WHERE root_mapping_id = :rid AND path = :path LIMIT 1"
            ),
            {"rid": root_mapping_id, "path": path},
        )
        return result.first() is not None


__all__ = ["DirtyScopeRecord", "DirtyScopeRepository"]
