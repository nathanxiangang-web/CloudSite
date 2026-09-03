"""Provider Capability 抽象层。"""

from .base import StorageProvider
from .capabilities import CAPABILITY_SCHEMA_VERSION, CapabilityState, ProviderCapabilities
from .alist_generic import GenericAListProvider
from .delta import (
    ProviderChange,
    ProviderCursorInvalid,
    DeltaSyncStrategy,
    RollingSyncStrategy,
    SyncStrategy,
    resolve_sync_strategy,
)
from .registry import DEFAULT_PROVIDER_TYPE, ProviderRegistry, registry

__all__ = [
    "StorageProvider",
    "CAPABILITY_SCHEMA_VERSION",
    "CapabilityState",
    "ProviderCapabilities",
    "GenericAListProvider",
    "ProviderChange",
    "ProviderCursorInvalid",
    "DeltaSyncStrategy",
    "RollingSyncStrategy",
    "SyncStrategy",
    "resolve_sync_strategy",
    "DEFAULT_PROVIDER_TYPE",
    "ProviderRegistry",
    "registry",
]
