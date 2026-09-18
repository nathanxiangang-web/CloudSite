"""SQLAlchemy adapter for Identity admin diagnostics queries."""

from __future__ import annotations

import json
from contextlib import AbstractAsyncContextManager
from typing import Callable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..application.admin_queries import IdentityAdminQueryRepository
from ..domain.admin_views import IdentityCandidateView, IdentityStatsView
from .models import (
    ResourceIdentity,
    ResourceIdentityCandidate,
    ResourceIdentityHistory,
)

SessionContextFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class SqlAlchemyIdentityAdminQueryRepository(IdentityAdminQueryRepository):
    def __init__(
        self,
        *,
        state_session: SessionContextFactory,
        index_session: SessionContextFactory,
    ) -> None:
        self._state_session = state_session
        self._index_session = index_session

    async def stats(self) -> IdentityStatsView:
        async with self._state_session() as state:
            total = int(
                await state.scalar(select(func.count()).select_from(ResourceIdentity))
                or 0
            )
            legacy = int(
                await state.scalar(
                    select(func.count())
                    .select_from(ResourceIdentity)
                    .where(ResourceIdentity.created_from == "legacy_migration")
                )
                or 0
            )
            history_rows = (
                await state.execute(
                    select(ResourceIdentityHistory.event_type, func.count())
                    .group_by(ResourceIdentityHistory.event_type)
                )
            ).all()

        history = {event_type: int(count) for event_type, count in history_rows}

        async with self._index_session() as index:
            candidate_rows = (
                await index.execute(
                    select(ResourceIdentityCandidate.status, func.count())
                    .group_by(ResourceIdentityCandidate.status)
                )
            ).all()

        candidates = {status: int(count) for status, count in candidate_rows}
        return IdentityStatsView(
            total=total,
            legacy_seeded=legacy,
            random_new=total - legacy,
            rename_preserved=history.get("rename", 0),
            move_preserved=history.get("move", 0),
            pending=candidates.get("pending", 0),
            ambiguous=candidates.get("ambiguous", 0),
            manual_repairs=history.get("manual_repair", 0),
        )

    async def candidates(
        self,
        *,
        status: str,
        limit: int,
    ) -> list[IdentityCandidateView]:
        statement = (
            select(ResourceIdentityCandidate)
            .order_by(ResourceIdentityCandidate.id.desc())
            .limit(limit)
        )
        if status == "open":
            statement = statement.where(
                ResourceIdentityCandidate.status.in_(("pending", "ambiguous"))
            )
        else:
            statement = statement.where(ResourceIdentityCandidate.status == status)

        async with self._index_session() as index:
            rows = list((await index.scalars(statement)).all())

        return [
            IdentityCandidateView(
                id=row.id,
                cycle_id=row.cycle_id,
                observed_path=row.observed_path,
                matched_resource_id=row.matched_resource_id,
                candidate_resource_ids=list(
                    json.loads(row.candidate_resource_ids_json or "[]")
                ),
                match_type=row.match_type,
                confidence=row.confidence,
                status=row.status,
                size=row.size,
                modified_at=row.modified_at,
                extension=row.extension,
                mime_type=row.mime_type,
                fingerprint=row.fingerprint,
                created_at=row.created_at,
                resolved_at=row.resolved_at,
            )
            for row in rows
        ]


__all__ = ["SqlAlchemyIdentityAdminQueryRepository"]
