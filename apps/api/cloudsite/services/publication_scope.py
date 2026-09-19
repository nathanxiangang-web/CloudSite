"""Backward-compatible shim for Catalog publication scope."""

from ..modules.catalog.application.publication_scope import (
    build_sitemap_xml,
    invalidate_sitemap_cache,
    is_publicly_visible,
    list_public_entries,
    public_entry_dto,
    set_publicly_visible,
    sitemap_entry_url,
)

__all__ = [
    "is_publicly_visible",
    "public_entry_dto",
    "list_public_entries",
    "set_publicly_visible",
    "sitemap_entry_url",
    "build_sitemap_xml",
    "invalidate_sitemap_cache",
]
