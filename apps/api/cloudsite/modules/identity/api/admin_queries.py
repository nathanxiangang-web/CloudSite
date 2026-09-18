"""Internal API wiring for admin Identity queries."""

from __future__ import annotations

from ....platform.db import index_session, state_session
from ..application.admin_queries import IdentityAdminQueries
from ..infrastructure.admin_query_repository import (
    SqlAlchemyIdentityAdminQueryRepository,
)


def _queries() -> IdentityAdminQueries:
    repository = SqlAlchemyIdentityAdminQueryRepository(
        state_session=state_session,
        index_session=index_session,
    )
    return IdentityAdminQueries(repository)


async def identity_stats_payload() -> dict[str, int]:
    return (await _queries().stats()).to_dict()


async def identity_candidates_payload(
    *,
    status: str,
    limit: int,
) -> dict[str, list[dict[str, object]]]:
    items = await _queries().candidates(status=status, limit=limit)
    return {"items": [item.to_dict() for item in items]}


__all__ = ["identity_candidates_payload", "identity_stats_payload"]
