"""Persistence-neutral User references for other business modules."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure.models import User


@dataclass(frozen=True, slots=True)
class UserReferenceView:
    id: int
    username: str
    status: str


async def user_references(
    state: AsyncSession,
    *,
    user_ids: list[int],
) -> dict[int, UserReferenceView]:
    ids = list(dict.fromkeys(user_ids))
    if not ids:
        return {}
    rows = list(
        (
            await state.scalars(
                select(User).where(User.id.in_(ids))
            )
        ).all()
    )
    return {
        row.id: UserReferenceView(
            id=row.id,
            username=row.username,
            status=row.status,
        )
        for row in rows
    }


__all__ = ["UserReferenceView", "user_references"]
