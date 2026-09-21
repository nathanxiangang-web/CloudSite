"""Provider sync state repository (V2 doc section 27).

Encapsulates CRUD over the provider_sync_state table, enabling
persistence of delta cursor and sync strategy per connection/root.
The repository uses text-based SQL only and does not import ORM
models, keeping the infrastructure free of ORM coupling.

All methods accept an AsyncSession and only flush; the caller commits
or rolls back the surrounding transaction.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_SYNC_STATE_FIELDS = (
    "id",
    "connection_id",
    "root_mapping_id",
    "strategy",
    "cursor",
    "cursor_version",
    "provider_generation",
    "last_delta_at",
    "last_full_verify_at",
    "status",
    "created_at",
    "updated_at",
)

_UPDATABLE_FIELDS = frozenset(
    {
        "strategy",
        "cursor",
        "cursor_version",
        "provider_generation",
        "last_delta_at",
        "last_full_verify_at",
        "status",
    }
)

_SELECT_COLUMNS = (
    "id, connection_id, root_mapping_id, strategy, cursor, "
    "cursor_version, provider_generation, last_delta_at, "
    "last_full_verify_at, status, created_at, updated_at"
)


@dataclass(frozen=True, slots=True)
class ProviderSyncStateRecord:
    """Immutable snapshot of one provider_sync_state row."""

    id: int
    connection_id: int
    root_mapping_id: int | None
    strategy: str
    cursor: str | None
    cursor_version: int
    provider_generation: str
    last_delta_at: str | None
    last_full_verify_at: str | None
    status: str
    created_at: str
    updated_at: str


def _row_to_record(row) -> ProviderSyncStateRecord:
    return ProviderSyncStateRecord(**{f: getattr(row, f) for f in _SYNC_STATE_FIELDS})


class ProviderSyncStateRepository:
    """Text-based SQL CRUD wrapper over provider_sync_state."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self, connection_id: int, root_mapping_id: int | None
    ) -> ProviderSyncStateRecord | None:
        result = await self._session.execute(
            text(
                f"SELECT {_SELECT_COLUMNS} FROM provider_sync_state "
                "WHERE connection_id = :cid AND root_mapping_id IS :rid"
            ),
            {"cid": connection_id, "rid": root_mapping_id},
        )
        row = result.first()
        return _row_to_record(row) if row else None

    async def upsert(
        self,
        connection_id: int,
        root_mapping_id: int | None,
        **fields: Any,
    ) -> None:
        """Insert or update a provider sync state row.

        For a new row, strategy defaults to 'rolling', cursor_version to 0,
        and status to 'idle' when omitted. For an existing row, only the
        supplied updatable fields are updated; updated_at is always refreshed.
        """
        for key in fields:
            if key not in _UPDATABLE_FIELDS:
                raise ValueError(f"unsupported sync_state field: {key!r}")

        existing = await self.get(connection_id, root_mapping_id)
        if existing is None:
            col_names = ["connection_id", "root_mapping_id"] + list(fields.keys())
            param_names = [":cid", ":rid"] + [f":{c}" for c in fields.keys()]
            await self._session.execute(
                text(
                    f"INSERT INTO provider_sync_state ({', '.join(col_names)}) "
                    f"VALUES ({', '.join(param_names)})"
                ),
                {"cid": connection_id, "rid": root_mapping_id, **fields},
            )
        else:
            if not fields:
                return
            set_parts = [f"{k} = :{k}" for k in fields]
            set_parts.append("updated_at = datetime('now')")
            await self._session.execute(
                text(
                    f"UPDATE provider_sync_state SET {', '.join(set_parts)} "
                    "WHERE connection_id = :cid AND root_mapping_id IS :rid"
                ),
                {"cid": connection_id, "rid": root_mapping_id, **fields},
            )
        await self._session.flush()

    async def update_cursor(
        self,
        connection_id: int,
        root_mapping_id: int | None,
        cursor: str,
        cursor_version: int | None = None,
    ) -> None:
        fields: dict[str, Any] = {
            "cursor": cursor,
            "last_delta_at": "datetime('now')",
        }
        if cursor_version is not None:
            fields["cursor_version"] = cursor_version

        set_parts = [f"cursor = :cursor", "last_delta_at = datetime('now')"]
        params: dict[str, Any] = {"cid": connection_id, "rid": root_mapping_id, "cursor": cursor}
        if cursor_version is not None:
            set_parts.append("cursor_version = :cv")
            params["cv"] = cursor_version
        set_parts.append("updated_at = datetime('now')")
        await self._session.execute(
            text(
                f"UPDATE provider_sync_state SET {', '.join(set_parts)} "
                "WHERE connection_id = :cid AND root_mapping_id IS :rid"
            ),
            params,
        )
        await self._session.flush()

    async def update_status(
        self,
        connection_id: int,
        root_mapping_id: int | None,
        status: str,
    ) -> None:
        await self._session.execute(
            text(
                "UPDATE provider_sync_state SET status = :status, "
                "updated_at = datetime('now') "
                "WHERE connection_id = :cid AND root_mapping_id IS :rid"
            ),
            {"cid": connection_id, "rid": root_mapping_id, "status": status},
        )
        await self._session.flush()

    async def delete(
        self, connection_id: int, root_mapping_id: int | None
    ) -> None:
        await self._session.execute(
            text(
                "DELETE FROM provider_sync_state "
                "WHERE connection_id = :cid AND root_mapping_id IS :rid"
            ),
            {"cid": connection_id, "rid": root_mapping_id},
        )
        await self._session.flush()


__all__ = ["ProviderSyncStateRecord", "ProviderSyncStateRepository"]