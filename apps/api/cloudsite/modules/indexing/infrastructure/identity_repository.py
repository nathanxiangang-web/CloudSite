"""Identity history persistence repository (V2 doc 22-23).

Text-based SQL only; does not import cloudsite.models to avoid
architecture-debt. The identity history table is created lazily via
``ensure_table`` so the repository is self-contained and usable from tests
without the full ORM metadata.

All methods accept an AsyncSession and only flush; the caller commits or
rolls back the surrounding transaction.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cloudsite.modules.indexing.domain.identity import (
    IdentityFingerprint,
    IdentityRecord,
)

_TABLE_SQL = """CREATE TABLE IF NOT EXISTS indexing_identity_history (
    id TEXT PRIMARY KEY,
    resource_id TEXT NOT NULL UNIQUE,
    root_mapping_id INTEGER NOT NULL,
    name TEXT,
    path TEXT,
    size INTEGER,
    modified_at TIMESTAMP,
    fingerprint TEXT NOT NULL,
    first_seen_at TIMESTAMP NOT NULL,
    last_seen_at TIMESTAMP NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
)"""

_SELECT_COLS = (
    "resource_id, fingerprint, root_mapping_id, name, path, "
    "size, modified_at, first_seen_at, last_seen_at, status"
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _row_to_record(row: Any) -> IdentityRecord:
    return IdentityRecord(
        resource_id=row.resource_id,
        fingerprint=row.fingerprint,
        root_mapping_id=row.root_mapping_id,
        name=row.name,
        path=row.path,
        size=row.size,
        modified_at=row.modified_at,
        first_seen_at=row.first_seen_at,
        last_seen_at=row.last_seen_at,
        status=row.status,
    )


class IdentityRepository:
    """Identity history persistence (text-based SQL, no ORM imports)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ensure_table(self) -> None:
        """Create the identity history table if it does not exist."""
        await self._session.execute(text(_TABLE_SQL))
        await self._session.flush()

    async def find_by_fingerprint(
        self,
        fingerprint: IdentityFingerprint,
    ) -> list[IdentityRecord]:
        """Return all active history records sharing the fingerprint digest.

        Scoped to the fingerprint's root_mapping_id. Since the digest already
        encodes the root, the root filter is redundant but kept for clarity.
        """
        result = await self._session.execute(
            text(
                f"SELECT {_SELECT_COLS} FROM indexing_identity_history "
                "WHERE fingerprint = :fp AND root_mapping_id = :rid "
                "ORDER BY resource_id"
            ),
            {"fp": fingerprint.digest, "rid": fingerprint.root_mapping_id},
        )
        return [_row_to_record(r) for r in result]

    async def save(
        self,
        resource_id: str,
        fingerprint: IdentityFingerprint,
        *,
        now: datetime | None = None,
    ) -> None:
        """Upsert a history record for resource_id with the given fingerprint."""
        ts = now or _utcnow()
        existing = await self.find_by_resource_id(resource_id)
        if existing is None:
            await self._session.execute(
                text(
                    "INSERT INTO indexing_identity_history "
                    "(id, resource_id, root_mapping_id, name, path, size, "
                    "modified_at, fingerprint, first_seen_at, last_seen_at, status) "
                    "VALUES (:id, :rid, :rmid, :name, :path, :size, :mod, :fp, "
                    ":ts, :ts, 'active')"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "rid": resource_id,
                    "rmid": fingerprint.root_mapping_id,
                    "name": fingerprint.name,
                    "path": fingerprint.path,
                    "size": fingerprint.size,
                    "mod": fingerprint.modified_at,
                    "fp": fingerprint.digest,
                    "ts": ts,
                },
            )
        else:
            await self._session.execute(
                text(
                    "UPDATE indexing_identity_history "
                    "SET root_mapping_id = :rmid, name = :name, path = :path, "
                    "size = :size, modified_at = :mod, fingerprint = :fp, "
                    "last_seen_at = :ts, status = 'active' "
                    "WHERE resource_id = :rid"
                ),
                {
                    "rid": resource_id,
                    "rmid": fingerprint.root_mapping_id,
                    "name": fingerprint.name,
                    "path": fingerprint.path,
                    "size": fingerprint.size,
                    "mod": fingerprint.modified_at,
                    "fp": fingerprint.digest,
                    "ts": ts,
                },
            )
        await self._session.flush()

    async def find_by_resource_id(
        self,
        resource_id: str,
    ) -> IdentityRecord | None:
        """Return the history record for resource_id, or None."""
        result = await self._session.execute(
            text(
                f"SELECT {_SELECT_COLS} FROM indexing_identity_history "
                "WHERE resource_id = :rid"
            ),
            {"rid": resource_id},
        )
        row = result.first()
        return _row_to_record(row) if row else None

    async def delete_by_resource_id(self, resource_id: str) -> None:
        """Delete the history record for resource_id, if any."""
        await self._session.execute(
            text(
                "DELETE FROM indexing_identity_history WHERE resource_id = :rid"
            ),
            {"rid": resource_id},
        )
        await self._session.flush()


__all__ = ["IdentityRepository"]
