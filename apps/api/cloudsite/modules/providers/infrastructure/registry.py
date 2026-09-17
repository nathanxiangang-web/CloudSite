from __future__ import annotations

from ....alist import AListClient
from ..domain.capabilities import ProviderCapabilities
from .alist_adapter import GenericAListProvider
from ..domain.provider import StorageProvider


DEFAULT_PROVIDER_TYPE = "generic_alist"


class ProviderRegistry:
    def resolve_type(self, provider_type: str | None) -> str:
        return provider_type if provider_type == DEFAULT_PROVIDER_TYPE else DEFAULT_PROVIDER_TYPE

    def wrap(self, client: AListClient, provider_type: str | None = None) -> StorageProvider:
        resolved = self.resolve_type(provider_type)
        if resolved == DEFAULT_PROVIDER_TYPE:
            return GenericAListProvider(client)
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


__all__ = ["DEFAULT_PROVIDER_TYPE", "ProviderRegistry", "registry"]