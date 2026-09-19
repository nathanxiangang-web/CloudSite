"""Stable public contract for the Search module."""

from ..application.service import (
    SearchRebuildResult,
    rebuild_public_search_index,
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
    "SEARCH_TYPES",
    "SEARCH_OBJECT_TYPES",
    "SEARCH_SORTS",
    "SearchRebuildResult",
    "normalize_search_query",
    "classify_match",
    "search_public_resources",
    "rebuild_public_search_index",
]
