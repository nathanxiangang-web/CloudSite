"""Provider 信息聚合：为后台 Capability 卡片与连接测试提供稳定摘要。"""

from __future__ import annotations

from ..database import StateSession
from ..models import AListConnection
from .delta import resolve_sync_strategy
from .registry import registry


async def provider_info() -> dict:
    async with StateSession() as session:
        connection = await session.get(AListConnection, 1)

    if connection is None:
        return {
            "provider_type": "generic_alist",
            "adapter_version": "generic_alist@1",
            "strategy": "rolling",
            "fallback_reason": "尚未配置 AList 连接",
            "capabilities": {},
        }

    provider_type = registry.resolve_type(connection.provider_type)
    capabilities = registry.capabilities_for(
        connection.provider_type, connection.provider_capabilities_json
    )
    strategy = resolve_sync_strategy(capabilities)
    fallback_reason = "" if strategy != "rolling" else "当前 Provider 未提供可靠 Delta Cursor"
    return {
        "provider_type": provider_type,
        "adapter_version": "generic_alist@1",
        "strategy": strategy,
        "fallback_reason": fallback_reason,
        "capabilities": capabilities.summary(),
    }
