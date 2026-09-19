"""Backward-compatible shim for Catalog public read projections."""

from ..modules.catalog.application.public_queries import (
    CatalogViewNotFound,
    catalog_asset_view,
    catalog_entry_view,
    catalog_release_view,
    public_catalog_asset_view,
    public_catalog_entry_view,
    public_catalog_release_view,
    published_catalog_page,
)

__all__ = [
    "CatalogViewNotFound",
    "catalog_asset_view",
    "catalog_entry_view",
    "catalog_release_view",
    "published_catalog_page",
    "public_catalog_entry_view",
    "public_catalog_release_view",
    "public_catalog_asset_view",
]
