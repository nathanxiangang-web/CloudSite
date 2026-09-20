"""Stable public contract for the Search module."""

from ..application.catalog_projection import (
    catalog_search_fts_match,
    consume_catalog_search_outbox,
    rebuild_catalog_search_index,
)
from ..application.service import (
    SearchRebuildResult,
    rebuild_public_search_index,
    recover_search_index_if_dirty,
    search_public_resources,
)
from ..domain.query import (
    SEARCH_OBJECT_TYPES,
    SEARCH_SORTS,
    SEARCH_TYPES,
    classify_match,
    normalize_search_query,
)

__all__ = [
    "catalog_search_fts_match",
    "consume_catalog_search_outbox",
    "rebuild_catalog_search_index",
    "SEARCH_TYPES",
    "SEARCH_OBJECT_TYPES",
    "SEARCH_SORTS",
    "SearchRebuildResult",
    "normalize_search_query",
    "classify_match",
    "search_public_resources",
    "rebuild_public_search_index",
    "recover_search_index_if_dirty",
]
