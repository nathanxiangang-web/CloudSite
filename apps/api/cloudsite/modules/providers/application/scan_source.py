"""Providers-owned composition for inventory scan sources."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....alist import AListClient
from ....crypto import decrypt_secret
from ..domain.scan import ProviderScanRoot, ProviderScanSource
from ..infrastructure.models import AListConnection, ContentRootMapping
from ..infrastructure.registry import registry


async def enabled_provider_scan_sources(
    session: AsyncSession,
) -> list[ProviderScanSource]:
    """Build enabled provider scan sources without exposing persistence state.

    The returned objects implement the provider-neutral scan protocol. Provider
    ORM rows, ciphertext, and decrypted credential strings remain local to this
    composition function and are not part of the public DTO surface.
    """
    sources: list[ProviderScanSource] = []
    connections = list(
        (
            await session.scalars(
                select(AListConnection)
                .where(AListConnection.enabled.is_(True))
                .order_by(AListConnection.id)
            )
        ).all()
    )
    for connection in connections:
        if not connection.password_ciphertext:
            continue
        root_rows = list(
            (
                await session.scalars(
                    select(ContentRootMapping)
                    .where(
                        ContentRootMapping.enabled.is_(True),
                        ContentRootMapping.connection_id == connection.id,
                    )
                    .order_by(
                        ContentRootMapping.sort_order,
                        ContentRootMapping.id,
                    )
                )
            ).all()
        )
        if not root_rows:
            continue

        client = AListClient(
            connection.base_url,
            connection.username,
            decrypt_secret(connection.password_ciphertext),
        )
        provider = registry.wrap(client, connection.provider_type)
        roots = tuple(
            ProviderScanRoot(
                root_mapping_id=row.id,
                content_type=row.content_type,
                display_name=row.display_name,
                storage_path=row.alist_path,
            )
            for row in root_rows
        )
        sources.append(
            ProviderScanSource(
                provider=provider,
                roots=roots,
            )
        )

    if not sources:
        raise RuntimeError("没有可用的已启用连接及内容根映射")
    return sources


__all__ = ["enabled_provider_scan_sources"]
