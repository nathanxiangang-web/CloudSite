from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure.models import AListConnection, ContentRootMapping
from ..domain.delta import resolve_sync_strategy
from ..infrastructure.registry import registry


@dataclass(frozen=True, slots=True)
class ProviderLoginTarget:
    """Minimal provider state needed by the admin credential check."""

    base_url: str


async def connection_login_target(
    session: AsyncSession,
) -> ProviderLoginTarget | None:
    connection = await session.get(AListConnection, 1)
    if connection is None:
        return None
    return ProviderLoginTarget(base_url=connection.base_url)


async def provider_info(session: AsyncSession) -> dict:
    connection = await session.get(AListConnection, 1)

    if connection is None:
        return {
            "provider_type": "generic_alist",
            "adapter_version": "generic_alist@1",
            "strategy": "rolling",
            "fallback_reason": "AList connection not configured",
            "capabilities": {},
        }

    provider_type = registry.resolve_type(connection.provider_type)
    capabilities = registry.capabilities_for(
        connection.provider_type, connection.provider_capabilities_json
    )
    strategy = resolve_sync_strategy(capabilities)
    fallback_reason = "" if strategy != "rolling" else "Provider does not offer a reliable delta cursor"
    return {
        "provider_type": provider_type,
        "adapter_version": "generic_alist@1",
        "strategy": strategy,
        "fallback_reason": fallback_reason,
        "capabilities": capabilities.summary(),
    }


async def enabled_root_ids(session: AsyncSession) -> set[int]:
    """Return enabled content-root ids without exposing provider ORM."""
    return set(
        (
            await session.scalars(
                select(ContentRootMapping.id).where(
                    ContentRootMapping.enabled.is_(True)
                )
            )
        ).all()
    )


__all__ = ["ProviderLoginTarget", "connection_login_target", "provider_info", "enabled_root_ids"]
