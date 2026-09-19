"""Public factory for read-only frozen legacy sync queries."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure.legacy_sync_queries import LegacySyncQueries


def legacy_sync_queries(session: AsyncSession) -> LegacySyncQueries:
    return LegacySyncQueries(session)


__all__ = ["legacy_sync_queries"]
