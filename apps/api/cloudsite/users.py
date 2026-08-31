from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .auth import auth_error, password_hash, user_dict, validate_password, validate_request_origin, validate_username
from .database import StateSession
from .models import OperationLog, User, utcnow
from .schemas import AdminPasswordResetInput, AdminUserCreateInput, AdminUserUpdateInput, UserStatusInput
from .sessions import revoke_user_sessions


router = APIRouter(prefix="/api/admin/users", tags=["admin-users"])


@router.get("")
async def list_users(
    search: str = Query(default="", max_length=100),
    status: str = Query(default="all", pattern=r"^(all|active|disabled|deleted)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    filters = []
    if search.strip():
        filters.append(User.username_normalized.contains(search.strip().lower()))
    if status == "all":
        filters.append(User.deleted_at.is_(None))
    elif status == "deleted":
        filters.append(User.deleted_at.is_not(None))
    else:
        filters.append(User.status == status)
        filters.append(User.deleted_at.is_(None))
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


@router.post("", status_code=201)
async def create_user(payload: AdminUserCreateInput, request: Request):
    validate_request_origin(request)
    username, normalized = validate_username(payload.username)
    password = validate_password(payload.password)
    if password != payload.password_confirm:
        raise auth_error(400, "PASSWORD_CONFIRM_MISMATCH", "两次输入的密码不一致")
    now = utcnow()
    async with StateSession() as session:
        if await session.scalar(select(User.id).where(User.username_normalized == normalized)):
            raise auth_error(409, "USERNAME_EXISTS", "用户名已存在")
        user = User(
            username=username,
            username_normalized=normalized,
            password_hash=password_hash.hash(password),
            status="active",
            created_at=now,
            updated_at=now,
            created_by_admin=True,
        )
        session.add(user)
        try:
            await session.flush()
            session.add(OperationLog(level="INFO", module="auth", action="admin_user_created", message=f"管理员创建用户 {user.username}"))
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise auth_error(409, "USERNAME_EXISTS", "用户名已存在") from exc
        await session.refresh(user)
        return user_dict(user)


@router.patch("/{user_id}")
async def update_user(user_id: int, payload: AdminUserUpdateInput, request: Request):
    validate_request_origin(request)
    username, normalized = validate_username(payload.username)
    async with StateSession() as session:
        user = await session.get(User, user_id)
        if not user:
            raise HTTPException(404, "用户不存在")
        if user.deleted_at is not None:
            raise auth_error(409, "USER_DELETED", "已删除用户不能编辑")
        conflict = await session.scalar(select(User.id).where(User.username_normalized == normalized, User.id != user_id))
        if conflict:
            raise auth_error(409, "USERNAME_EXISTS", "用户名已存在")
        old_username = user.username
        user.username = username
        user.username_normalized = normalized
        user.updated_at = utcnow()
        session.add(OperationLog(level="INFO", module="auth", action="admin_user_updated", message=f"管理员将用户 {old_username} 改名为 {username}"))
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise auth_error(409, "USERNAME_EXISTS", "用户名已存在") from exc
        await session.refresh(user)
        return user_dict(user)


@router.patch("/{user_id}/status")
async def update_user_status(user_id: int, payload: UserStatusInput, request: Request):
    validate_request_origin(request)
    async with StateSession() as session:
        user = await session.get(User, user_id)
        if not user:
            raise HTTPException(404, "用户不存在")
        if user.deleted_at is not None:
            raise auth_error(409, "USER_DELETED", "已删除用户不能修改状态")
        now = utcnow()
        user.status = payload.status
        user.disabled_at = now if payload.status == "disabled" else None
        user.updated_at = now
        if payload.status == "disabled":
            await revoke_user_sessions(session, user.id, now)
        action = "user_disabled" if payload.status == "disabled" else "user_enabled"
        session.add(OperationLog(level="INFO", module="auth", action=action, message=f"管理员将用户 {user.username} 设置为 {payload.status}"))
        await session.commit()
        await session.refresh(user)
        return user_dict(user)


@router.post("/{user_id}/reset-password")
async def reset_user_password(user_id: int, payload: AdminPasswordResetInput, request: Request):
    validate_request_origin(request)
    password = validate_password(payload.new_password, field_name="新密码")
    if password != payload.new_password_confirm:
        raise auth_error(400, "PASSWORD_CONFIRM_MISMATCH", "两次输入的新密码不一致")
    async with StateSession() as session:
        user = await session.get(User, user_id)
        if not user:
            raise HTTPException(404, "用户不存在")
        if user.deleted_at is not None:
            raise auth_error(409, "USER_DELETED", "已删除用户不能重置密码")
        now = utcnow()
        user.password_hash = password_hash.hash(password)
        user.password_changed_at = now
        user.updated_at = now
        await revoke_user_sessions(session, user.id, now)
        session.add(OperationLog(level="INFO", module="auth", action="admin_password_reset", message=f"管理员重置用户 {user.username} 的密码"))
        await session.commit()
    return {"ok": True}


@router.delete("/{user_id}")
async def delete_user(user_id: int, request: Request):
    validate_request_origin(request)
    async with StateSession() as session:
        user = await session.get(User, user_id)
        if not user:
            raise HTTPException(404, "用户不存在")
        if user.deleted_at is None:
            now = utcnow()
            user.deleted_at = now
            user.disabled_at = now
            user.status = "disabled"
            user.updated_at = now
            await revoke_user_sessions(session, user.id, now)
            session.add(OperationLog(level="INFO", module="auth", action="admin_user_deleted", message=f"管理员软删除用户 {user.username}"))
            await session.commit()
    return {"ok": True}
