from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..domain.inspection import InspectionRequest, InspectionResult
from ..domain.snapshot import SnapshotEntry


@dataclass(slots=True, frozen=True)
class ProviderCapabilities:
    supports_scan: bool = True
    supports_pagination: bool = True
    supports_inspect: bool = True
    supports_content_hash: bool = False
    supports_recursive_list: bool = False
    max_page_size: int | None = None


@runtime_checkable
class ProviderAdapter(Protocol):
    """Capability-driven adapter for a content provider.

    Implementations advertise capabilities via the capabilities property and
    services consult those flags before invoking optional operations. This
    keeps provider integration explicit and avoids silent degradation when a
    provider cannot support an operation.
    """

    @property
    def provider_id(self) -> str: ...

    @property
    def capabilities(self) -> ProviderCapabilities: ...

    async def scan_category(
        self,
        category_id: str,
        *,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> tuple[list[SnapshotEntry], str | None, bool]:
        """Scan one category page.

        Returns (entries, next_cursor, pagination_complete). When
        pagination_complete is False the caller knows the category was not
        fully enumerated and must not treat absent entries as removed.
        """
        ...

    async def inspect(self, request: InspectionRequest) -> InspectionResult:
        """Inspect a single resource for fresh detail and metadata."""
        ...


__all__ = ['ProviderCapabilities', 'ProviderAdapter']