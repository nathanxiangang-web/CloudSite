from __future__ import annotations

from ..api.parser_seed import parser_seed_changes, parser_seed_run
from ..domain.parser_seed import ParserSeedChangeView, ParserSeedRunView
from typing import Protocol, runtime_checkable

from ..application.reconcile import ReconcileResult
from ..domain.inspection import InspectionRequest, InspectionResult
from ..domain.snapshot import CategorySnapshot


@runtime_checkable
class IndexingServicePort(Protocol):
    """Public port for the indexing module.

    Consumers depend on this protocol rather than concrete services, so the
    indexing module can evolve its internals without breaking callers.
    """

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
    "ParserSeedRunView",
    "ParserSeedChangeView",
    "parser_seed_run",
    "parser_seed_changes",
]