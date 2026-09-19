"""Provider runtime contracts and persistence-neutral results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class ProviderUnavailableError(RuntimeError):
    """Configured root/provider is not currently available."""


class ProviderAccessError(RuntimeError):
    """Provider operation failed without exposing backend-specific exceptions."""

    def __init__(
        self,
        category: str,
        message: str = "provider operation failed",
        *,
        status_code: int = 502,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class ProviderEntry:
    url: str
    host: str
    base_path: str = "/"
    has_sign: bool = False


@runtime_checkable
class ProviderRuntimePort(Protocol):
    async def download_entry(
        self,
        *,
        root_mapping_id: int,
        path: str,
    ) -> ProviderEntry: ...

    async def preview_entry(
        self,
        *,
        root_mapping_id: int,
        path: str,
    ) -> ProviderEntry: ...


__all__ = [
    "ProviderAccessError",
    "ProviderEntry",
    "ProviderRuntimePort",
    "ProviderUnavailableError",
]
