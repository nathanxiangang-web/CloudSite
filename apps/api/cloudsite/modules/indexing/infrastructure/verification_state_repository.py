"""Durable per-directory rolling verification state (V2 sections 32-34)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class VerificationStateRecord:
    root_mapping_id: int
    path: str
    fingerprint: str | None
    child_count: int
    last_verified_at: str | None
    last_changed_at: str | None
    last_error_code: str | None
    last_error_message: str | None
    created_at: str
    updated_at: str


_SELECT_COLUMNS = (
    "root_mapping_id, path, fingerprint, child_count, last_verified_at, "
    "last_changed_at, last_error_code, last_error_message, created_at, updated_at"
)

_UPDATABLE_FIELDS = frozenset(
    {
        "fingerprint",
        "child_count",
        "last_verified_at",
        "last_changed_at",
        "last_error_code",
        "last_error_message",
    }
)


def _row_to_record(row) -> VerificationStateRecord:
    return VerificationStateRecord(
        root_mapping_id=row.root_mapping_id,
        path=row.path,
        fingerprint=row.fingerprint,
        child_count=row.child_count,
        last_verified_at=row.last_verified_at,
        last_changed_at=row.last_changed_at,
        last_error_code=row.last_error_code,
        last_error_message=row.last_error_message,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class VerificationStateRepository:
    """CRUD for durable verification facts.

    This repository does not own dirty-work scheduling. A mismatch should be
    recorded in index_dirty_scopes by the production verification service.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self,
        root_mapping_id: int,
        path: str,
    ) -> VerificationStateRecord | None:
        result = await self._session.execute(
            text(
                f"SELECT {_SELECT_COLUMNS} FROM index_verification_states "
                "WHERE root_mapping_id = :rid AND path = :path"
            ),
            {"rid": root_mapping_id, "path": path},
        )
        row = result.first()
        return _row_to_record(row) if row else None

    async def upsert(
        self,
        root_mapping_id: int,
        path: str,
        **fields,
    ) -> None:
        for key in fields:
            if key not in _UPDATABLE_FIELDS:
                raise ValueError(f"unsupported verification_state field: {key!r}")

        existing = await self.get(root_mapping_id, path)
        if existing is None:
            columns = ["root_mapping_id", "path"] + list(fields)
            params = [":rid", ":path"] + [f":{name}" for name in fields]
            await self._session.execute(
                text(
                    f"INSERT INTO index_verification_states ({', '.join(columns)}) "
                    f"VALUES ({', '.join(params)})"
                ),
                {"rid": root_mapping_id, "path": path, **fields},
            )
        elif fields:
            assignments = [f"{name} = :{name}" for name in fields]
            assignments.append("updated_at = datetime('now')")
            await self._session.execute(
                text(
                    f"UPDATE index_verification_states "
                    f"SET {', '.join(assignments)} "
                    "WHERE root_mapping_id = :rid AND path = :path"
                ),
                {"rid": root_mapping_id, "path": path, **fields},
            )
        await self._session.flush()

    async def mark_verified(
        self,
        root_mapping_id: int,
        path: str,
        *,
        fingerprint: str,
        child_count: int,
        changed: bool = False,
        verified_at: str | None = None,
    ) -> None:
        when = verified_at or _utcnow_iso()
        fields: dict[str, object] = {
            "fingerprint": fingerprint,
            "child_count": max(int(child_count), 0),
            "last_verified_at": when,
            "last_error_code": None,
            "last_error_message": None,
        }
        if changed:
            fields["last_changed_at"] = when
        await self.upsert(root_mapping_id, path, **fields)

    async def mark_failed(
        self,
        root_mapping_id: int,
        path: str,
        *,
        error_code: str,
        error_message: str,
    ) -> None:
        await self.upsert(
            root_mapping_id,
            path,
            last_error_code=error_code,
            last_error_message=error_message,
        )

    async def list_for_root(
        self,
        root_mapping_id: int,
    ) -> list[VerificationStateRecord]:
        result = await self._session.execute(
            text(
                f"SELECT {_SELECT_COLUMNS} FROM index_verification_states "
                "WHERE root_mapping_id = :rid "
                "ORDER BY "
                "CASE WHEN last_verified_at IS NULL THEN 0 ELSE 1 END, "
                "last_verified_at, path"
            ),
            {"rid": root_mapping_id},
        )
        return [_row_to_record(row) for row in result]

    async def delete(
        self,
        root_mapping_id: int,
        path: str,
    ) -> None:
        await self._session.execute(
            text(
                "DELETE FROM index_verification_states "
                "WHERE root_mapping_id = :rid AND path = :path"
            ),
            {"rid": root_mapping_id, "path": path},
        )
        await self._session.flush()


__all__ = ["VerificationStateRecord", "VerificationStateRepository"]
