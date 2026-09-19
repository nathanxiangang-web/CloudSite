"""Admin content-root mapping lifecycle owned by Providers."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ....alist import AListClient
from ....crypto import decrypt_secret
from .connection_admin import ProviderAdminError, _mapped_error
from ..infrastructure.models import AListConnection, ContentRootMapping


def normalize_provider_path(value: str) -> str:
    path = str(value or "").strip().replace("\\", "/")
    path = re.sub(r"/+", "/", f"/{path.lstrip('/')}")
    return path.rstrip("/") or "/"


def _mapping_payload(row: ContentRootMapping) -> dict[str, Any]:
    return {
        "id": row.id,
        "connection_id": row.connection_id,
        "content_type": row.content_type,
        "display_name": row.display_name,
        "alist_path": row.alist_path,
        "enabled": row.enabled,
        "sort_order": row.sort_order,
    }


async def list_root_mappings(
    state: AsyncSession,
) -> list[dict[str, Any]]:
    rows = list(
        (
            await state.scalars(
                select(ContentRootMapping).order_by(
                    ContentRootMapping.sort_order
                )
            )
        ).all()
    )
    return [_mapping_payload(row) for row in rows]


async def validate_root_mapping_path(
    state: AsyncSession,
    *,
    path: str,
    connection_id: int = 1,
) -> str:
    normalized = normalize_provider_path(path)
    connection = await state.get(AListConnection, connection_id)
    if (
        connection is None
        or not connection.enabled
        or not connection.password_ciphertext
    ):
        raise ProviderAdminError(
            "请先保存可用的 AList 连接和凭据",
            status_code=409,
        )
    try:
        client = AListClient(
            connection.base_url,
            connection.username,
            decrypt_secret(connection.password_ciphertext),
        )
        info = await client.get_path(normalized)
    except Exception as exc:
        raise _mapped_error(exc) from exc
    if info.get("is_dir") is False:
        raise ProviderAdminError(
            "根目录映射必须指向 AList 文件夹",
            status_code=400,
        )
    return normalized


async def create_root_mapping(
    state: AsyncSession,
    *,
    values: dict[str, Any],
    validated_path: str | None = None,
) -> int:
    normalized = validated_path
    if normalized is None:
        normalized = await validate_root_mapping_path(
            state,
            path=str(values.get("alist_path") or ""),
            connection_id=int(values.get("connection_id") or 1),
        )
    row = ContentRootMapping(
        **{**values, "alist_path": normalized}
    )
    state.add(row)
    try:
        await state.commit()
    except IntegrityError as exc:
        await state.rollback()
        raise ProviderAdminError(
            "该 AList 根目录已存在",
            status_code=409,
        ) from exc
    await state.refresh(row)
    return int(row.id)


async def update_root_mapping(
    state: AsyncSession,
    mapping_id: int,
    *,
    values: dict[str, Any],
    validated_path: str | None = None,
) -> None:
    normalized = validated_path
    if normalized is None:
        normalized = await validate_root_mapping_path(
            state,
            path=str(values.get("alist_path") or ""),
            connection_id=int(values.get("connection_id") or 1),
        )
    row = await state.get(ContentRootMapping, mapping_id)
    if row is None:
        raise ProviderAdminError(
            "映射不存在",
            status_code=404,
        )
    for key, value in {**values, "alist_path": normalized}.items():
        setattr(row, key, value)
    try:
        await state.commit()
    except IntegrityError as exc:
        await state.rollback()
        raise ProviderAdminError(
            "该 AList 根目录已被其他映射使用",
            status_code=409,
        ) from exc


async def delete_root_mapping(
    state: AsyncSession,
    mapping_id: int,
) -> None:
    row = await state.get(ContentRootMapping, mapping_id)
    if row is None:
        raise ProviderAdminError(
            "映射不存在",
            status_code=404,
        )
    await state.delete(row)
    await state.commit()


__all__ = [
    "normalize_provider_path",
    "list_root_mappings",
    "validate_root_mapping_path",
    "create_root_mapping",
    "update_root_mapping",
    "delete_root_mapping",
]
