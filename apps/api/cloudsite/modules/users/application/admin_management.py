"""Users-owned administrator account management workflows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import ceil
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ....platform.observability import write_operation_log
from ..domain.credentials import (
    CredentialPolicyError,
    validate_password,
    validate_username,
)
from ..infrastructure.models import User, utcnow
from .authentication import password_hash
from .session_service import revoke_user_sessions_state


class UserAdminError(RuntimeError):
    def __init__(
        self,
        status_code: int,
        message: str,
        *,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class UserAdminView:
    id: int
    username: str
    status: str
    created_at: datetime
    last_login_at: datetime | None
    password_changed_at: datetime | None
    disabled_at: datetime | None
    deleted_at: datetime | None
    created_by_admin: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "username": self.username,
            "status": (
                "deleted"
                if self.deleted_at is not None
                else self.status
            ),
            "created_at": self.created_at,
            "last_login_at": self.last_login_at,
            "password_changed_at": self.password_changed_at,
            "disabled_at": self.disabled_at,
            "deleted_at": self.deleted_at,
            "created_by_admin": self.created_by_admin,
        }


def _view(user: User) -> UserAdminView:
    return UserAdminView(
        id=user.id,
        username=user.username,
        status=user.status,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        password_changed_at=user.password_changed_at,
        disabled_at=user.disabled_at,
        deleted_at=user.deleted_at,
        created_by_admin=bool(user.created_by_admin),
    )


def _not_found() -> UserAdminError:
    return UserAdminError(404, "用户不存在")


def _deleted(message: str) -> UserAdminError:
    return UserAdminError(
        409,
        message,
        code="USER_DELETED",
    )


def _credential_error(
    exc: CredentialPolicyError,
) -> UserAdminError:
    return UserAdminError(
        exc.status_code,
        exc.message,
        code=exc.code,
    )


async def list_admin_users(
    state: AsyncSession,
    *,
    search: str = "",
    status: str = "all",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    filters = []
    if search.strip():
        filters.append(
            User.username_normalized.contains(
                search.strip().lower()
            )
        )
    if status == "all":
        filters.append(User.deleted_at.is_(None))
    elif status == "deleted":
        filters.append(User.deleted_at.is_not(None))
    else:
        filters.append(User.status == status)
        filters.append(User.deleted_at.is_(None))

    total = int(
        await state.scalar(
            select(func.count())
            .select_from(User)
            .where(*filters)
        )
        or 0
    )
    rows = list(
        (
            await state.scalars(
                select(User)
                .where(*filters)
                .order_by(User.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return {
        "items": [_view(user).to_dict() for user in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": ceil(total / page_size) if total else 0,
    }


async def get_admin_user(
    state: AsyncSession,
    *,
    user_id: int,
) -> dict[str, Any]:
    user = await state.get(User, user_id)
    if user is None:
        raise _not_found()
    return _view(user).to_dict()


async def create_admin_user(
    state: AsyncSession,
    *,
    username: str,
    password: str,
) -> dict[str, Any]:
    try:
        username, normalized = validate_username(username)
        password = validate_password(password)
    except CredentialPolicyError as exc:
        raise _credential_error(exc) from exc

    if await state.scalar(
        select(User.id).where(
            User.username_normalized == normalized
        )
    ):
        raise UserAdminError(
            409,
            "用户名已存在",
            code="USERNAME_EXISTS",
        )

    now = utcnow()
    user = User(
        username=username,
        username_normalized=normalized,
        password_hash=password_hash.hash(password),
        status="active",
        created_at=now,
        updated_at=now,
        created_by_admin=True,
    )
    state.add(user)
    try:
        await state.flush()
        await write_operation_log(
            state,
            module="auth",
            action="admin_user_created",
            message=f"管理员创建用户 {user.username}",
        )
        await state.commit()
    except IntegrityError as exc:
        await state.rollback()
        raise UserAdminError(
            409,
            "用户名已存在",
            code="USERNAME_EXISTS",
        ) from exc

    await state.refresh(user)
    return _view(user).to_dict()


async def rename_admin_user(
    state: AsyncSession,
    *,
    user_id: int,
    username: str,
) -> dict[str, Any]:
    try:
        username, normalized = validate_username(username)
    except CredentialPolicyError as exc:
        raise _credential_error(exc) from exc

    user = await state.get(User, user_id)
    if user is None:
        raise _not_found()
    if user.deleted_at is not None:
        raise _deleted("已删除用户不能编辑")

    conflict = await state.scalar(
        select(User.id).where(
            User.username_normalized == normalized,
            User.id != user_id,
        )
    )
    if conflict:
        raise UserAdminError(
            409,
            "用户名已存在",
            code="USERNAME_EXISTS",
        )

    old_username = user.username
    user.username = username
    user.username_normalized = normalized
    user.updated_at = utcnow()
    await write_operation_log(
        state,
        module="auth",
        action="admin_user_updated",
        message=(
            f"管理员将用户 {old_username} 改名为 {username}"
        ),
    )
    try:
        await state.commit()
    except IntegrityError as exc:
        await state.rollback()
        raise UserAdminError(
            409,
            "用户名已存在",
            code="USERNAME_EXISTS",
        ) from exc
    await state.refresh(user)
    return _view(user).to_dict()


async def set_admin_user_status(
    state: AsyncSession,
    *,
    user_id: int,
    status: str,
) -> dict[str, Any]:
    user = await state.get(User, user_id)
    if user is None:
        raise _not_found()
    if user.deleted_at is not None:
        raise _deleted("已删除用户不能修改状态")

    now = utcnow()
    user.status = status
    user.disabled_at = (
        now if status == "disabled" else None
    )
    user.updated_at = now
    if status == "disabled":
        await revoke_user_sessions_state(
            state,
            user_id=user.id,
            now=now,
        )

    action = (
        "user_disabled"
        if status == "disabled"
        else "user_enabled"
    )
    await write_operation_log(
        state,
        module="auth",
        action=action,
        message=(
            f"管理员将用户 {user.username} 设置为 {status}"
        ),
    )
    await state.commit()
    await state.refresh(user)
    return _view(user).to_dict()


async def reset_admin_user_password(
    state: AsyncSession,
    *,
    user_id: int,
    new_password: str,
) -> None:
    try:
        password = validate_password(
            new_password,
            field_name="新密码",
        )
    except CredentialPolicyError as exc:
        raise _credential_error(exc) from exc

    user = await state.get(User, user_id)
    if user is None:
        raise _not_found()
    if user.deleted_at is not None:
        raise _deleted("已删除用户不能重置密码")

    now = utcnow()
    user.password_hash = password_hash.hash(password)
    user.password_changed_at = now
    user.updated_at = now
    await revoke_user_sessions_state(
        state,
        user_id=user.id,
        now=now,
    )
    await write_operation_log(
        state,
        module="auth",
        action="admin_password_reset",
        message=f"管理员重置用户 {user.username} 的密码",
    )
    await state.commit()


async def delete_admin_user(
    state: AsyncSession,
    *,
    user_id: int,
) -> None:
    user = await state.get(User, user_id)
    if user is None:
        raise _not_found()
    if user.deleted_at is not None:
        return

    now = utcnow()
    user.deleted_at = now
    user.disabled_at = now
    user.status = "disabled"
    user.updated_at = now
    await revoke_user_sessions_state(
        state,
        user_id=user.id,
        now=now,
    )
    await write_operation_log(
        state,
        module="auth",
        action="admin_user_deleted",
        message=f"管理员软删除用户 {user.username}",
    )
    await state.commit()


__all__ = [
    "UserAdminError",
    "UserAdminView",
    "create_admin_user",
    "delete_admin_user",
    "get_admin_user",
    "list_admin_users",
    "rename_admin_user",
    "reset_admin_user_password",
    "set_admin_user_status",
]
