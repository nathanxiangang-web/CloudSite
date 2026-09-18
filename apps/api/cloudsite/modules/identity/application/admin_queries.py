"""Admin identity query application service."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.admin_views import IdentityCandidateView, IdentityStatsView


@runtime_checkable
class IdentityAdminQueryRepository(Protocol):
    async def stats(self) -> IdentityStatsView: ...

    async def candidates(
        self,
        *,
        status: str,
        limit: int,
    ) -> list[IdentityCandidateView]: ...


class IdentityAdminQueries:
    def __init__(self, repository: IdentityAdminQueryRepository) -> None:
        self._repository = repository

    async def stats(self) -> IdentityStatsView:
        return await self._repository.stats()

    async def candidates(
        self,
        *,
        status: str,
        limit: int,
    ) -> list[IdentityCandidateView]:
        return await self._repository.candidates(status=status, limit=limit)


__all__ = ["IdentityAdminQueries", "IdentityAdminQueryRepository"]
