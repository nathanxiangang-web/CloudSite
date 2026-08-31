from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import func, select

from .auth import user_dict, validate_request_origin
from .database import StateSession
from .models import OperationLog, User, utcnow
from .schemas import UserStatusInput
from .sessions import revoke_user_sessions


router = APIRouter(prefix="/api/admin/users", tags=["admin-users"])


@router.get("")
async def list_users(
    search: str = Query(default="", max_length=100),
    status: str = Query(default="all", pattern=r"^(all|active|disabled)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    filters = []
    if search.strip():
        filters.append(User.username_normalized.contains(search.strip().lower()))
    if status != "all":
        filters.append(User.status == status)
    async with StateSession() as session:
        total = int(await session.scalar(select(func.count()).select_from(User).where(*filters)) or 0)
        rows = list(
            (
                await session.scalars(
                    select(User)
                    .where(*filters)
                    .order_by(User.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
    return {
        "items": [user_dict(user) for user in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": (total + page_size - 1) // page_size,
    }


@router.get("/{user_id}")
async def get_user(user_id: int):
    async with StateSession() as session:
        user = await session.get(User, user_id)
        if not user:
            raise HTTPException(404, "用户不存在")
        return user_dict(user)


@router.patch("/{user_id}/status")
async def update_user_status(user_id: int, payload: UserStatusInput, request: Request):
    validate_request_origin(request)
    async with StateSession() as session:
        user = await session.get(User, user_id)
        if not user:
            raise HTTPException(404, "用户不存在")
        now = utcnow()
        user.status = payload.status
        user.updated_at = now
        if payload.status == "disabled":
            await revoke_user_sessions(session, user.id, now)
        action = "user_disabled" if payload.status == "disabled" else "user_enabled"
        session.add(OperationLog(level="INFO", module="auth", action=action, message=f"管理员将用户 {user.username} 设置为 {payload.status}"))
        await session.commit()
        await session.refresh(user)
        return user_dict(user)
