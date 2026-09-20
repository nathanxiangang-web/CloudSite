"""User role query/update application boundary."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.roles import validate_role
from ..infrastructure.models import User, utcnow


class UserRoleNotFound(RuntimeError):
    pass


def user_role_view(user: User) -> dict[str, Any]:
    return {
        "user_id": user.id,
        "username": user.username,
        "role": user.role,
        "status": user.status,
    }


async def list_user_role_views(
    state: AsyncSession,
) -> list[dict[str, Any]]:
    users = list(
        (
            await state.scalars(
                select(User).order_by(User.id)
            )
        ).all()
    )
    return [user_role_view(user) for user in users]


async def set_user_role(
    state: AsyncSession,
    *,
    user_id: int,
    role: str,
) -> dict[str, Any]:
    validated = validate_role(role)
    user = await state.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise UserRoleNotFound(user_id)

    user.role = validated
    user.updated_at = utcnow()
    await state.commit()
    await state.refresh(user)
    return user_role_view(user)


__all__ = [
    "UserRoleNotFound",
    "user_role_view",
    "list_user_role_views",
    "set_user_role",
]
