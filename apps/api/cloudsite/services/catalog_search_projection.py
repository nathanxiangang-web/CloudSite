"""Compatibility facade for Catalog -> Search projection.

Catalog owns the outbox/source side. Search owns FTS persistence, projection
watermarks, consumption, and rebuild orchestration. Historical imports remain
stable through this module while callers migrate to module contracts.
"""

from ..modules.catalog.contracts.public import enqueue_catalog_search_outbox
from ..modules.search.contracts.public import (
    catalog_search_fts_match,
    consume_catalog_search_outbox,
    rebuild_catalog_search_index,
)


__all__ = [
    "enqueue_catalog_search_outbox",
    "catalog_search_fts_match",
    "consume_catalog_search_outbox",
    "rebuild_catalog_search_index",
]
