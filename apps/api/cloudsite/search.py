"""Compatibility facade for the Search module.

Production query/rebuild/recovery behavior is owned by modules/search. This
legacy import surface keeps query-policy symbols and startup recovery available
for callers that have not yet switched imports, but contains no implementation.
"""

from .modules.search.contracts.public import recover_search_index_if_dirty
from .modules.search.domain.query import (
    SEARCH_OBJECT_TYPES,
    SEARCH_SORTS,
    SEARCH_TYPES,
    build_fts_query,
    classify_match,
    escape_like,
    normalize_search_query,
)


__all__ = [
    "SEARCH_TYPES",
    "SEARCH_OBJECT_TYPES",
    "SEARCH_SORTS",
    "build_fts_query",
    "classify_match",
    "escape_like",
    "normalize_search_query",
    "recover_search_index_if_dirty",
]
