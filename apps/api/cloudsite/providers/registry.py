"""Provider Registry：根据 Connection 选择 Adapter。

未知 Provider 一律回退 generic_alist，绝不自动启用 Delta。
"""

from __future__ import annotations

from ..alist import AListClient
from .alist_generic import GenericAListProvider
from .base import StorageProvider
from .capabilities import ProviderCapabilities


DEFAULT_PROVIDER_TYPE = "generic_alist"


class ProviderRegistry:
    def resolve_type(self, provider_type: str | None) -> str:
        return provider_type if provider_type == DEFAULT_PROVIDER_TYPE else DEFAULT_PROVIDER_TYPE

    def wrap(self, client: AListClient, provider_type: str | None = None) -> StorageProvider:
        resolved = self.resolve_type(provider_type)
        if resolved == DEFAULT_PROVIDER_TYPE:
            return GenericAListProvider(client)
        # 未来 Provider 类型在这里按需扩展；未知类型仍回退 generic。
        return GenericAListProvider(client)

    def capabilities_for(self, provider_type: str | None, stored_json: str | None) -> ProviderCapabilities:
        resolved = self.resolve_type(provider_type)
        if resolved != DEFAULT_PROVIDER_TYPE:
            return ProviderCapabilities()
        stored = ProviderCapabilities.from_json(stored_json)
        if stored.capability_schema_version != ProviderCapabilities().capability_schema_version:
            return ProviderCapabilities()
        return stored


registry = ProviderRegistry()
