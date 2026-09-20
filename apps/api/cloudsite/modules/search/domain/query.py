"""Search query policy and persistence-neutral candidates."""

from __future__ import annotations

import re
from dataclasses import dataclass

SEARCH_TYPES = {"software", "image", "video", "document", "file"}
SEARCH_OBJECT_TYPES = {"all", "resource", "folder"}
SEARCH_SORTS = {"relevance", "modified_at", "name", "size"}


def normalize_search_query(value: str) -> str:
    return " ".join(value.strip().split())


def escape_like(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def build_fts_query(value: str) -> str:
    tokens = re.findall(r"[0-9A-Za-z\u0080-\uffff]+", value)[:8]
    return " AND ".join(
        f'"{token.replace(chr(34), chr(34) * 2)}"*'
        for token in tokens
    )


def classify_match(name: str, query: str) -> str:
    lowered_name = name.casefold()
    lowered_query = query.casefold()
    if lowered_name == lowered_query:
        return "exact"
    if lowered_name.startswith(lowered_query):
        return "prefix"
    if lowered_query in lowered_name:
        return "name"
    return "metadata"


@dataclass(frozen=True, slots=True)
class SearchCandidate:
    object_id: str
    object_type: str
    name: str
    extension: str
    content_type: str
    relevance: int


__all__ = [
    "SEARCH_TYPES",
    "SEARCH_OBJECT_TYPES",
    "SEARCH_SORTS",
    "SearchCandidate",
    "normalize_search_query",
    "escape_like",
    "build_fts_query",
    "classify_match",
]
