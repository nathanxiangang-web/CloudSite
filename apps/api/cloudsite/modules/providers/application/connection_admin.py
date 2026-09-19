"""Admin provider-connection lifecycle owned by Providers."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....alist import AListClient, AListError
from ....crypto import decrypt_secret, encrypt_secret
from ....platform.observability import write_operation_log
from ..infrastructure.models import AListConnection, utcnow


class ProviderAdminError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int = 502,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _mapped_error(
    exc: Exception,
    *,
    fallback_status: int = 502,
) -> ProviderAdminError:
    if isinstance(exc, AListError):
        return ProviderAdminError(
            str(exc),
            code=exc.code,
            status_code=exc.status_code,
        )
    if isinstance(exc, ValueError):
        return ProviderAdminError(
            str(exc),
            code="AL-006",
            status_code=400,
        )
    return ProviderAdminError(
        "AList 操作失败，请稍后重试",
        code="AL-999",
        status_code=fallback_status,
    )


def _settings_payload(row: AListConnection | None) -> dict[str, Any]:
    if row is None:
        return {
            "base_url": "",
            "username": "",
            "remember_credentials": True,
            "enabled": False,
            "connection_status": "unconfigured",
            "last_test_status": "untested",
            "last_test_message": "",
            "last_test_at": None,
            "has_password": False,
        }
    return {
        "base_url": row.base_url,
        "username": row.username,
        "remember_credentials": row.remember_credentials,
        "enabled": row.enabled,
        "connection_status": (
            "connected"
            if row.enabled and row.last_test_status == "success"
            else "disconnected"
        ),
        "last_test_status": row.last_test_status,
        "last_test_message": row.last_test_message,
        "last_test_at": row.last_test_at,
        "has_password": bool(row.password_ciphertext),
    }


async def admin_connection_settings(
    state: AsyncSession,
) -> dict[str, Any]:
    return _settings_payload(await state.get(AListConnection, 1))


def _stored_password(row: AListConnection | None) -> str:
    if row is None or not row.password_ciphertext:
        return ""
    try:
        return decrypt_secret(row.password_ciphertext)
    except ValueError as exc:
        raise _mapped_error(exc, fallback_status=400) from exc


async def test_admin_connection(
    state: AsyncSession,
    *,
    base_url: str,
    username: str,
    password: str,
) -> dict[str, Any]:
    row = await state.get(AListConnection, 1)
    resolved_password = password or _stored_password(row)
    try:
        if not resolved_password:
            raise AListError(
                "请输入 AList 密码",
                "AL-004",
                status_code=400,
                auth_failed=True,
            )
        result = await AListClient(
            base_url,
            username,
            resolved_password,
        ).test()
    except Exception as exc:
        status_row = row or AListConnection(id=1)
        status_row.last_test_status = "failed"
        status_row.last_test_message = str(exc)
        status_row.last_test_at = utcnow()
        state.add(status_row)
        await write_operation_log(
            state,
            level="ERROR",
            module="alist",
            action="test",
            message=f"AList 连接测试失败：{str(exc)[:300]}",
        )
        await state.commit()
        raise _mapped_error(exc, fallback_status=400) from exc

    status_row = row or AListConnection(id=1)
    status_row.last_test_status = "success"
    status_row.last_test_message = str(result["message"])
    status_row.last_test_at = utcnow()
    status_row.base_path = str(result.get("base_path") or "/")
    state.add(status_row)
    await write_operation_log(
        state,
        module="alist",
        action="test",
        message=(
            "AList 连接测试成功，根目录包含 "
            f"{int(result['item_count'])} 项"
        ),
    )
    await state.commit()
    return result


async def save_admin_connection(
    state: AsyncSession,
    *,
    base_url: str,
    username: str,
    password: str,
    remember_credentials: bool,
) -> dict[str, Any]:
    row = await state.get(AListConnection, 1) or AListConnection(id=1)
    resolved_password = password or _stored_password(row)
    if not resolved_password:
        raise ProviderAdminError(
            "请输入 AList 密码",
            status_code=400,
        )

    try:
        result = await AListClient(
            base_url,
            username,
            resolved_password,
        ).test()
    except Exception as exc:
        row.last_test_status = "failed"
        row.last_test_message = str(exc)
        row.last_test_at = utcnow()
        state.add(row)
        await write_operation_log(
            state,
            level="ERROR",
            module="alist",
            action="save",
            message=f"AList 设置验证失败：{str(exc)[:300]}",
        )
        await state.commit()
        raise _mapped_error(exc, fallback_status=400) from exc

    row.base_url = base_url.rstrip("/")
    row.base_path = str(result.get("base_path") or "/")
    row.username = username
    row.password_ciphertext = (
        encrypt_secret(resolved_password)
        if remember_credentials
        else ""
    )
    row.remember_credentials = remember_credentials
    row.enabled = True
    row.last_test_status = "success"
    row.last_test_message = "AList 连接及根目录访问成功"
    row.last_test_at = utcnow()
    state.add(row)
    await write_operation_log(
        state,
        module="alist",
        action="save",
        message="AList 连接设置已验证并保存",
    )
    await state.commit()
    return {"ok": True, "message": "AList 设置已保存"}


async def browse_admin_directories(
    state: AsyncSession,
    *,
    path: str,
) -> dict[str, Any]:
    normalized_path = "/" + path.strip().strip("/")
    if normalized_path == "//":
        normalized_path = "/"

    row = await state.get(AListConnection, 1)
    if row is None or not row.enabled:
        raise ProviderAdminError(
            "请先连接并保存 AList 设置",
            status_code=409,
        )
    if not row.password_ciphertext:
        raise ProviderAdminError(
            "当前未保存 AList 登录凭据，请重新保存连接并启用记住登录信息",
            status_code=409,
        )

    try:
        client = AListClient(
            row.base_url,
            row.username,
            decrypt_secret(row.password_ciphertext),
        )
        directories = await client.list_directories(normalized_path)
    except Exception as exc:
        raise _mapped_error(exc) from exc

    def directory_path(name: str) -> str:
        if normalized_path == "/":
            return f"/{name}"
        return f"{normalized_path}/{name}"

    parent_path = (
        "/"
        if normalized_path == "/"
        else normalized_path.rsplit("/", 1)[0] or "/"
    )
    return {
        "path": normalized_path,
        "parent_path": parent_path,
        "items": [
            {
                "name": str(item["name"]),
                "path": directory_path(str(item["name"])),
                "modified": item.get("modified"),
            }
            for item in directories
        ],
    }


async def check_provider_health(
    state: AsyncSession,
) -> tuple[str, str | None]:
    """Readiness probe for the configured provider connection."""

    try:
        row = await state.get(AListConnection, 1)
    except Exception as exc:
        return "degraded", str(exc)
    if row is None or not row.enabled:
        return "healthy", None
    try:
        password = decrypt_secret(row.password_ciphertext)
        async with AListClient(
            row.base_url,
            row.username,
            password,
        ) as client:
            await client.test()
        return "healthy", None
    except Exception as exc:
        return "degraded", str(exc)


__all__ = [
    "ProviderAdminError",
    "admin_connection_settings",
    "test_admin_connection",
    "save_admin_connection",
    "browse_admin_directories",
    "check_provider_health",
]
