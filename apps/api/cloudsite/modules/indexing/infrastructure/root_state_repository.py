"""Root state repository (V2 doc sections 6-7).

Encapsulates CRUD over the index_root_states table introduced in R5 PR01 so
that each Content Root owns an independent index lifecycle state row. The
repository uses text-based SQL only and does not import cloudsite.models,
keeping the indexing infrastructure free of ORM coupling (architecture-debt
avoidance).

All methods accept an AsyncSession and only flush; the caller commits or
rolls back the surrounding transaction.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_ROOT_STATE_FIELDS = (
    "root_mapping_id",
    "connection_id",
    "status",
    "generation",
    "bootstrap_completed_at",
    "last_change_at",
    "last_verified_at",
    "last_full_audit_at",
    "last_reconcile_at",
    "change_cursor",
    "provider_revision",
    "scan_fingerprint",
    "last_error_code",
    "last_error_message",
    "created_at",
    "updated_at",
)

_UPDATABLE_FIELDS = frozenset(
    {
        "connection_id",
        "status",
        "generation",
        "bootstrap_completed_at",
        "last_change_at",
        "last_verified_at",
        "last_full_audit_at",
        "last_reconcile_at",
        "change_cursor",
        "provider_revision",
        "scan_fingerprint",
        "last_error_code",
        "last_error_message",
    }
)

_SELECT_COLUMNS = (
    "root_mapping_id, connection_id, status, generation, "
    "bootstrap_completed_at, last_change_at, last_verified_at, "
    "last_full_audit_at, last_reconcile_at, change_cursor, "
    "provider_revision, scan_fingerprint, last_error_code, "
    "last_error_message, created_at, updated_at"
)


@dataclass(frozen=True, slots=True)
class RootStateRecord:
    """Immutable snapshot of one index_root_states row."""

    root_mapping_id: int
    connection_id: int
    status: str
    generation: int
    bootstrap_completed_at: str | None
    last_change_at: str | None
    last_verified_at: str | None
    last_full_audit_at: str | None
    last_reconcile_at: str | None
    change_cursor: str | None
    provider_revision: str | None
    scan_fingerprint: str | None
    last_error_code: str | None
    last_error_message: str | None
    created_at: str
    updated_at: str


def _row_to_record(row) -> RootStateRecord:
    return RootStateRecord(**{f: getattr(row, f) for f in _ROOT_STATE_FIELDS})


class RootStateRepository:
    """Text-based SQL CRUD wrapper over index_root_states."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, root_mapping_id: int) -> RootStateRecord | None:
        result = await self._session.execute(
            text(
                f"SELECT {_SELECT_COLUMNS} FROM index_root_states "
                "WHERE root_mapping_id = :rid"
            ),
            {"rid": root_mapping_id},
        )
        row = result.first()
        return _row_to_record(row) if row else None

    async def upsert(self, root_mapping_id: int, **fields: Any) -> None:
        """Insert or update a root state row.

        For a new row, connection_id must be supplied in fields (the column
        is NOT NULL with no default). status defaults to 'bootstrap_required'
        and generation to 0 when omitted. For an existing row, only the
        supplied updatable fields are updated; updated_at is always refreshed.
        """
        for key in fields:
            if key not in _UPDATABLE_FIELDS:
                raise ValueError(f"unsupported root_state field: {key!r}")

        existing = await self.get(root_mapping_id)
        if existing is None:
            if "connection_id" not in fields:
                raise ValueError(
                    "connection_id is required when creating a new root state"
                )
            col_names = ["root_mapping_id"] + list(fields.keys())
            param_names = [":rid"] + [f":{c}" for c in fields.keys()]
            await self._session.execute(
                text(
                    f"INSERT INTO index_root_states ({', '.join(col_names)}) "
                    f"VALUES ({', '.join(param_names)})"
                ),
                {"rid": root_mapping_id, **fields},
            )
        else:
            if not fields:
                return
            set_parts = [f"{k} = :{k}" for k in fields]
            set_parts.append("updated_at = datetime('now')")
            await self._session.execute(
                text(
                    f"UPDATE index_root_states SET {', '.join(set_parts)} "
                    "WHERE root_mapping_id = :rid"
                ),
                {"rid": root_mapping_id, **fields},
            )
        await self._session.flush()

    async def update_status(self, root_mapping_id: int, status: str) -> None:
        await self._session.execute(
            text(
                "UPDATE index_root_states SET status = :status, "
                "updated_at = datetime('now') WHERE root_mapping_id = :rid"
            ),
            {"rid": root_mapping_id, "status": status},
        )
        await self._session.flush()

    async def find_by_status(self, status: str) -> list[RootStateRecord]:
        result = await self._session.execute(
            text(
                f"SELECT {_SELECT_COLUMNS} FROM index_root_states "
                "WHERE status = :status ORDER BY root_mapping_id"
            ),
            {"status": status},
        )
        return [_row_to_record(r) for r in result]

    async def delete(self, root_mapping_id: int) -> None:
        await self._session.execute(
            text("DELETE FROM index_root_states WHERE root_mapping_id = :rid"),
            {"rid": root_mapping_id},
        )
        await self._session.flush()


__all__ = ["RootStateRecord", "RootStateRepository"]
