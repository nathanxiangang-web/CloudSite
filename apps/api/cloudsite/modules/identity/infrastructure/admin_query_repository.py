"""SQLAlchemy-backed admin query adapter for Identity."""

from __future__ import annotations

from sqlalchemy import func, select

from ....platform.db import index_session, state_session
from ..application.ports import IdentityAdminQueryRepository
from ..domain.records import IdentityCandidateRecord
from .models import (
    ResourceIdentity,
    ResourceIdentityCandidate,
    ResourceIdentityHistory,
)


class SqlAlchemyIdentityAdminQueryRepository(IdentityAdminQueryRepository):
    async def identity_counts(self) -> tuple[int, int]:
        async with state_session() as state:
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
        return total, legacy

    async def history_counts(self) -> dict[str, int]:
        async with state_session() as state:
            rows = (
                await state.execute(
                    select(ResourceIdentityHistory.event_type, func.count())
                    .group_by(ResourceIdentityHistory.event_type)
                )
            ).all()
        return {event_type: int(count) for event_type, count in rows}

    async def candidate_status_counts(self) -> dict[str, int]:
        async with index_session() as index:
            rows = (
                await index.execute(
                    select(ResourceIdentityCandidate.status, func.count())
                    .group_by(ResourceIdentityCandidate.status)
                )
            ).all()
        return {status: int(count) for status, count in rows}

    async def list_candidates(
        self,
        statuses: set[str],
        limit: int,
    ) -> list[IdentityCandidateRecord]:
        statement = (
            select(ResourceIdentityCandidate)
            .order_by(ResourceIdentityCandidate.id.desc())
            .limit(limit)
        )
        if len(statuses) == 1:
            statement = statement.where(
                ResourceIdentityCandidate.status == next(iter(statuses))
            )
        else:
            statement = statement.where(
                ResourceIdentityCandidate.status.in_(tuple(sorted(statuses)))
            )
        async with index_session() as index:
            rows = list((await index.scalars(statement)).all())
        return [
            IdentityCandidateRecord(
                id=row.id,
                cycle_id=row.cycle_id,
                observed_path=row.observed_path,
                matched_resource_id=row.matched_resource_id,
                candidate_resource_ids_json=row.candidate_resource_ids_json,
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
