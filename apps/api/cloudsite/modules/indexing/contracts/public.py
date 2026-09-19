from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..api.admin_status import (
    indexing_v2_enabled,
    read_sync_circuit_status,
    read_v2_sync_progress,
    toggle_automatic_sync,
)
from ..api.legacy_sync import legacy_sync_queries
from ..application.reconcile import ReconcileResult
from ..domain.inspection import InspectionRequest, InspectionResult
from ..domain.legacy_sync import (
    LegacySyncChangePage,
    LegacySyncChangeView,
    LegacySyncRunView,
)
from ..domain.snapshot import CategorySnapshot


@runtime_checkable
class IndexingServicePort(Protocol):
    """Public port for the indexing module."""

    async def scan_category(self, category_id: str) -> CategorySnapshot:
        """Inventory scan for a category, returns a point-in-time snapshot."""
        ...

    async def inspect_resource(
        self, resource_id: str, *, provider_id: str
    ) -> InspectionResult:
        """Detail inspection for a single resource."""
        ...

    async def reconcile_snapshot(self, snapshot: CategorySnapshot) -> ReconcileResult:
        """Reconcile a snapshot with persisted state and apply changes."""
        ...


__all__ = [
    "IndexingServicePort",
    "LegacySyncRunView",
    "LegacySyncChangeView",
    "LegacySyncChangePage",
    "legacy_sync_queries",
    "indexing_v2_enabled",
    "read_v2_sync_progress",
    "read_sync_circuit_status",
    "toggle_automatic_sync",
]
