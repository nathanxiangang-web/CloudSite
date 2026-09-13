"""X1 连接管理服务：多连接 CRUD + Provider 兼容记录。

多连接命名空间：每个 ContentRootMapping 属于一个 connection_id。
旧数据归到默认连接 (id=1)。不同来源同路径不合并。
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..crypto import decrypt_secret, encrypt_secret
from ..models import AListConnection, ContentRootMapping, OperationLog, ProviderCompatRecord, utcnow


@dataclass(frozen=True, slots=True)
class ConnectionResult:
    ok: bool
    message: str
    connection_id: int | None = None


async def list_connections(session: AsyncSession) -> list[AListConnection]:
    rows = await session.scalars(select(AListConnection).order_by(AListConnection.id))
    return list(rows.all())


async def get_connection(session: AsyncSession, connection_id: int) -> AListConnection | None:
    return await session.get(AListConnection, connection_id)


async def create_connection(
    session: AsyncSession,
    *,
    name: str,
    base_url: str,
    username: str,
    password: str,
    remember_credentials: bool = True,
    provider_type: str = "generic_alist",
) -> ConnectionResult:
    conn = AListConnection(
        name=name,
        base_url=base_url.rstrip("/"),
        username=username,
        password_ciphertext=encrypt_secret(password) if remember_credentials else "",
        remember_credentials=remember_credentials,
        enabled=False,
        provider_type=provider_type,
    )
    session.add(conn)
    session.add(OperationLog(module="connections", action="create", message=f"创建连接 {name}"))
    await session.commit()
    await session.refresh(conn)
    return ConnectionResult(ok=True, message="连接已创建", connection_id=conn.id)


async def update_connection(
    session: AsyncSession,
    connection_id: int,
    *,
    name: str | None = None,
    base_url: str | None = None,
    username: str | None = None,
    password: str | None = None,
    remember_credentials: bool | None = None,
    provider_type: str | None = None,
) -> ConnectionResult:
    conn = await session.get(AListConnection, connection_id)
    if not conn:
        return ConnectionResult(ok=False, message="连接不存在")
    if name is not None:
        conn.name = name
    if base_url is not None:
        conn.base_url = base_url.rstrip("/")
    if username is not None:
        conn.username = username
    if password is not None and password:
        conn.password_ciphertext = encrypt_secret(password) if (remember_credentials if remember_credentials is not None else conn.remember_credentials) else ""
    if remember_credentials is not None:
        conn.remember_credentials = remember_credentials
        if not remember_credentials:
            conn.password_ciphertext = ""
    if provider_type is not None:
        conn.provider_type = provider_type
    session.add(conn)
    session.add(OperationLog(module="connections", action="update", message=f"更新连接 {conn.name}"))
    await session.commit()
    return ConnectionResult(ok=True, message="连接已更新", connection_id=connection_id)


async def toggle_connection(
    session: AsyncSession,
    connection_id: int,
    enabled: bool,
) -> ConnectionResult:
    conn = await session.get(AListConnection, connection_id)
    if not conn:
        return ConnectionResult(ok=False, message="连接不存在")
    conn.enabled = enabled
    session.add(conn)
    session.add(
        OperationLog(
            module="connections",
            action="toggle",
            message=f"连接 {conn.name} {'启用' if enabled else '禁用'}",
        )
    )
    await session.commit()
    return ConnectionResult(ok=True, message=f"连接已{'启用' if enabled else '禁用'}", connection_id=connection_id)


async def delete_connection(session: AsyncSession, connection_id: int) -> ConnectionResult:
    if connection_id == 1:
        return ConnectionResult(ok=False, message="默认连接不可删除")
    conn = await session.get(AListConnection, connection_id)
    if not conn:
        return ConnectionResult(ok=False, message="连接不存在")
    root_count = await session.scalar(
        select(ContentRootMapping.id).where(ContentRootMapping.connection_id == connection_id).limit(1)
    )
    if root_count:
        return ConnectionResult(ok=False, message="该连接仍有内容根映射，无法删除")
    await session.delete(conn)
    session.add(OperationLog(module="connections", action="delete", message=f"删除连接 {conn.name}"))
    await session.commit()
    return ConnectionResult(ok=True, message="连接已删除", connection_id=connection_id)


async def list_compat_records(session: AsyncSession) -> list[ProviderCompatRecord]:
    rows = await session.scalars(
        select(ProviderCompatRecord).order_by(ProviderCompatRecord.created_at.desc())
    )
    return list(rows.all())


async def record_compat(
    session: AsyncSession,
    *,
    provider_type: str,
    adapter_version: str,
    platform: str,
    platform_version: str = "",
    test_result: str = "pass",
    tested_capabilities_json: str = "",
    notes: str = "",
) -> ProviderCompatRecord:
    record = ProviderCompatRecord(
        id=f"pcr_{secrets.token_hex(16)}",
        provider_type=provider_type,
        adapter_version=adapter_version,
        platform=platform,
        platform_version=platform_version,
        test_result=test_result,
        tested_capabilities_json=tested_capabilities_json,
        notes=notes,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record


async def get_connection_roots(session: AsyncSession, connection_id: int) -> list[ContentRootMapping]:
    rows = await session.scalars(
        select(ContentRootMapping)
        .where(ContentRootMapping.connection_id == connection_id, ContentRootMapping.enabled.is_(True))
        .order_by(ContentRootMapping.sort_order, ContentRootMapping.id)
    )
    return list(rows.all())


async def all_enabled_connections(session: AsyncSession) -> list[AListConnection]:
    rows = await session.scalars(
        select(AListConnection)
        .where(AListConnection.enabled.is_(True))
        .order_by(AListConnection.id)
    )
    return list(rows.all())