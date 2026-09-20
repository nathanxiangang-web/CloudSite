"""Single-user boundary for cloud-drive organization operations.

The backend chooses the user by ID. A disabled or missing designation grants no
organization privileges. The scheduler also checks this boundary before moving
files; ordinary cloud-download submissions do not use it.
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import User


def require_organizer_actor(user: User) -> None:
    """Allow only the one active backend-designated CloudSite user."""
    configured_id = settings.organizer_user_id
    if (
        configured_id <= 0
        or user.id != configured_id
        or user.status != "active"
        or user.deleted_at is not None
        or user.disabled_at is not None
    ):
        raise HTTPException(
            status_code=403,
            detail={"code": "ORGANIZER_FORBIDDEN", "message": "整理权限未开放"},
        )


async def active_organizer_user(state: AsyncSession) -> User | None:
    """Return the designated user only while the account remains active."""
    configured_id = settings.organizer_user_id
    if configured_id <= 0:
        return None
    user = await state.get(User, configured_id)
    if user is None:
        return None
    try:
        require_organizer_actor(user)
    except HTTPException:
        return None
    return user
