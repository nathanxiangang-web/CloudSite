"""Users-owned public authentication workflows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ....platform.observability import write_operation_log
from .session_service import (
    AuthenticatedUserView,
    create_user_session_state,
    revoke_session_state,
    revoke_user_sessions_state,
)
from ..infrastructure.models import User, utcnow


password_hash = PasswordHash.recommended()


class UserAuthenticationError(RuntimeError):
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


@dataclass(frozen=True, slots=True)
class AuthenticationResult:
    user: AuthenticatedUserView
    token: str


def verify_password(value: str, encoded: str) -> bool:
    try:
        return password_hash.verify(value, encoded)
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


async def register_user(
    state: AsyncSession,
    *,
    username: str,
    username_normalized: str,
    password: str,
    created_ip_hash: str | None = None,
    user_agent_hash: str | None = None,
    now: datetime | None = None,
) -> AuthenticationResult:
    current = now or utcnow()
    if await state.scalar(
        select(User.id).where(
            User.username_normalized == username_normalized
        )
    ):
        raise UserAuthenticationError(
            409,
            "USERNAME_EXISTS",
            "用户名已存在",
        )

    user = User(
        username=username,
        username_normalized=username_normalized,
        password_hash=password_hash.hash(password),
        status="active",
        created_at=current,
        updated_at=current,
        last_login_at=current,
    )
    state.add(user)
    try:
        await state.flush()
        _, token = await create_user_session_state(
            state,
            user_id=user.id,
            now=current,
            created_ip_hash=created_ip_hash,
            user_agent_hash=user_agent_hash,
        )
        await write_operation_log(
            state,
            module="auth",
            action="user_registered",
            message=f"用户 {user.username} 完成注册",
        )
        await state.commit()
    except IntegrityError as exc:
        await state.rollback()
        raise UserAuthenticationError(
            409,
            "USERNAME_EXISTS",
            "用户名已存在",
        ) from exc

    await state.refresh(user)
    return AuthenticationResult(
        user=_user_view(user),
        token=token,
    )


async def login_user(
    state: AsyncSession,
    *,
    username_normalized: str,
    password: str,
    created_ip_hash: str | None = None,
    user_agent_hash: str | None = None,
    now: datetime | None = None,
) -> AuthenticationResult:
    user = (
        await state.scalar(
            select(User).where(
                User.username_normalized == username_normalized
            )
        )
        if username_normalized
        else None
    )
    if (
        user is None
        or user.deleted_at is not None
        or not verify_password(password, user.password_hash)
    ):
        await write_operation_log(
            state,
            level="WARNING",
            module="auth",
            action="user_login_failed",
            message="前台用户登录失败",
        )
        await state.commit()
        raise UserAuthenticationError(
            401,
            "INVALID_CREDENTIALS",
            "用户名或密码错误",
        )

    if user.status != "active":
        raise UserAuthenticationError(
            403,
            "USER_DISABLED",
            "当前账号已被停用",
        )

    current = now or utcnow()
    user.last_login_at = current
    _, token = await create_user_session_state(
        state,
        user_id=user.id,
        now=current,
        created_ip_hash=created_ip_hash,
        user_agent_hash=user_agent_hash,
    )
    await write_operation_log(
        state,
        module="auth",
        action="user_login_success",
        message=f"用户 {user.username} 登录成功",
    )
    await state.commit()
    await state.refresh(user)
    return AuthenticationResult(
        user=_user_view(user),
        token=token,
    )


async def logout_user(
    state: AsyncSession,
    *,
    token: str | None,
    now: datetime | None = None,
) -> None:
    await revoke_session_state(
        state,
        token=token,
        now=now,
    )
    await write_operation_log(
        state,
        module="auth",
        action="user_logout",
        message="前台用户退出登录",
    )
    await state.commit()


async def change_user_password(
    state: AsyncSession,
    *,
    user_id: int,
    current_password: str,
    new_password: str,
    created_ip_hash: str | None = None,
    user_agent_hash: str | None = None,
    now: datetime | None = None,
) -> AuthenticationResult:
    user = await state.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise UserAuthenticationError(
            401,
            "USER_DELETED",
            "账号不存在或已被删除",
        )
    if not verify_password(
        current_password,
        user.password_hash,
    ):
        raise UserAuthenticationError(
            400,
            "CURRENT_PASSWORD_INVALID",
            "当前密码错误",
        )

    current = now or utcnow()
    user.password_hash = password_hash.hash(new_password)
    user.password_changed_at = current
    user.updated_at = current
    await revoke_user_sessions_state(
        state,
        user_id=user.id,
        now=current,
    )
    _, token = await create_user_session_state(
        state,
        user_id=user.id,
        now=current,
        created_ip_hash=created_ip_hash,
        user_agent_hash=user_agent_hash,
    )
    await write_operation_log(
        state,
        module="auth",
        action="password_changed",
        message=f"用户 {user.username} 修改密码",
    )
    await state.commit()
    await state.refresh(user)
    return AuthenticationResult(
        user=_user_view(user),
        token=token,
    )


__all__ = [
    "AuthenticationResult",
    "UserAuthenticationError",
    "change_user_password",
    "login_user",
    "logout_user",
    "password_hash",
    "register_user",
    "verify_password",
]
