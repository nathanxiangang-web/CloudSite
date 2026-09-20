"""Stable public contract for the Collections module."""

from ..application.service import (
    CollectionError,
    CollectionNotFound,
    CollectionValidationError,
    collection_contains_resource,
    collection_publication_scope,
    collection_view,
    create_collection,
    delete_collection,
    get_admin_collection,
    get_public_collection,
    list_admin_collections,
    list_home_collections,
    list_public_collections,
    replace_collection_items,
    update_collection,
)

__all__ = [
    "CollectionError",
    "CollectionNotFound",
    "CollectionValidationError",
    "collection_contains_resource",
    "collection_publication_scope",
    "collection_view",
    "list_public_collections",
    "list_home_collections",
    "get_public_collection",
    "list_admin_collections",
    "get_admin_collection",
    "create_collection",
    "update_collection",
    "replace_collection_items",
    "delete_collection",
]
