"""User account authentication workflows owned by Users."""

from __future__ import annotations

from datetime import datetime

from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ....platform.observability import write_operation_log
from .session_service import (
    AuthenticatedUserView,
    revoke_user_sessions_state,
)
from ..infrastructure.models import User, utcnow


_password_hash = PasswordHash.recommended()


class UserAuthWorkflowError(RuntimeError):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _verify_password(value: str, encoded: str) -> bool:
    try:
        return _password_hash.verify(value, encoded)
    except Exception:
        return False


def _user_view(row: User) -> AuthenticatedUserView:
    return AuthenticatedUserView(
        id=row.id,
        username=row.username,
        status=row.status,
        created_at=row.created_at,
        last_login_at=row.last_login_at,
        password_changed_at=row.password_changed_at,
        disabled_at=row.disabled_at,
        deleted_at=row.deleted_at,
        created_by_admin=bool(row.created_by_admin),
        role=row.role or "viewer",
    )


async def register_user_account(
    state: AsyncSession,
    *,
    username: str,
    username_normalized: str,
    password: str,
    now: datetime | None = None,
) -> AuthenticatedUserView:
    existing = await state.scalar(
        select(User.id).where(
            User.username_normalized == username_normalized
        )
    )
    if existing is not None:
        raise UserAuthWorkflowError(
            409,
            "USERNAME_EXISTS",
            "用户名已存在",
        )

    current = now or utcnow()
    user = User(
        username=username,
        username_normalized=username_normalized,
        password_hash=_password_hash.hash(password),
        status="active",
        created_at=current,
        updated_at=current,
        last_login_at=current,
    )
    state.add(user)
    try:
        await state.flush()
    except IntegrityError as exc:
        await state.rollback()
        raise UserAuthWorkflowError(
            409,
            "USERNAME_EXISTS",
            "用户名已存在",
        ) from exc

    await write_operation_log(
        state,
        module="auth",
        action="user_registered",
        message=f"用户 {user.username} 完成注册",
    )
    return _user_view(user)


async def authenticate_user_account(
    state: AsyncSession,
    *,
    username_normalized: str,
    password: str,
    now: datetime | None = None,
) -> AuthenticatedUserView:
    user = (
        await state.scalar(
            select(User).where(
                User.username_normalized
                == username_normalized
            )
        )
        if username_normalized
        else None
    )
    if (
        user is None
        or user.deleted_at is not None
        or not _verify_password(password, user.password_hash)
    ):
        await write_operation_log(
            state,
            module="auth",
            action="user_login_failed",
            message="前台用户登录失败",
            level="WARNING",
        )
        await state.commit()
        raise UserAuthWorkflowError(
            401,
            "INVALID_CREDENTIALS",
            "用户名或密码错误",
        )
    if user.status != "active":
        raise UserAuthWorkflowError(
            403,
            "USER_DISABLED",
            "当前账号已被停用",
        )

    current = now or utcnow()
    user.last_login_at = current
    await write_operation_log(
        state,
        module="auth",
        action="user_login_success",
        message=f"用户 {user.username} 登录成功",
    )
    return _user_view(user)


async def change_user_password(
    state: AsyncSession,
    *,
    user_id: int,
    current_password: str,
    new_password: str,
    now: datetime | None = None,
) -> AuthenticatedUserView:
    user = await state.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise UserAuthWorkflowError(
            401,
            "USER_DELETED",
            "账号不存在或已被删除",
        )
    if user.status != "active":
        raise UserAuthWorkflowError(
            403,
            "USER_DISABLED",
            "当前账号已被停用",
        )
    if not _verify_password(
        current_password,
        user.password_hash,
    ):
        raise UserAuthWorkflowError(
            400,
            "CURRENT_PASSWORD_INVALID",
            "当前密码错误",
        )

    current = now or utcnow()
    user.password_hash = _password_hash.hash(new_password)
    user.password_changed_at = current
    user.updated_at = current
    await revoke_user_sessions_state(
        state,
        user_id=user.id,
        now=current,
    )
    await write_operation_log(
        state,
        module="auth",
        action="password_changed",
        message=f"用户 {user.username} 修改密码",
    )
    return _user_view(user)


__all__ = [
    "UserAuthWorkflowError",
    "authenticate_user_account",
    "change_user_password",
    "register_user_account",
]
