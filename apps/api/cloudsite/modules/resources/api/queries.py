"""Internal wiring for Resources list queries."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..application.queries import ResourceQueries
from ..infrastructure.query_repository import SqlAlchemyResourceQueryRepository


def resource_queries(session: AsyncSession) -> ResourceQueries:
    return ResourceQueries(SqlAlchemyResourceQueryRepository(session))


__all__ = ["resource_queries"]
