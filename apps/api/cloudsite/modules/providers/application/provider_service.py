from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure.models import AListConnection
from ..domain.delta import resolve_sync_strategy
from ..infrastructure.registry import registry


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


__all__ = ["provider_info"]