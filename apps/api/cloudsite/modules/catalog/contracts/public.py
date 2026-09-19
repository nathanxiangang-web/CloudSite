"""Public contract symbols for the Catalog module.

Exposes the domain exceptions and result dataclasses that form the stable
public API of the catalog application layer. Routers and external callers
depend on these types; the function implementations live in
application/catalog_entry.py and application/catalog_release.py.
"""
from __future__ import annotations

from ..application.catalog_entry import (
    CatalogAssetNotDownloadable,
    CatalogEntryNotFound,
    CatalogError,
    CatalogPublishValidationFailed,
    CatalogRevisionConflict,
    CatalogSlugConflict,
    CreateCatalogEntryResult,
    LocationResolution,
    PreviewValidationResult,
    PublishCatalogEntryResult,
)
from ..application.catalog_release import (
    AssetDownloadTarget,
    AttachCatalogLocationResult,
    CatalogAssetNotFound,
    CatalogLocationInvalid,
    CatalogReleaseNotFound,
    CreateCatalogAssetResult,
    CreateCatalogReleaseResult,
)

__all__ = [
    # exceptions
    "CatalogError",
    "CatalogEntryNotFound",
    "CatalogReleaseNotFound",
    "CatalogAssetNotFound",
    "CatalogRevisionConflict",
    "CatalogSlugConflict",
    "CatalogLocationInvalid",
    "CatalogPublishValidationFailed",
    "CatalogAssetNotDownloadable",
    # result dataclasses
    "CreateCatalogEntryResult",
    "CreateCatalogReleaseResult",
    "CreateCatalogAssetResult",
    "LocationResolution",
    "AttachCatalogLocationResult",
    "PreviewValidationResult",
    "PublishCatalogEntryResult",
    "AssetDownloadTarget",
    "CatalogSuggestionContext",
    "CatalogSuggestionMutation",
    "CatalogSuggestionRevisionView",
    "apply_suggestion_asset",
    "apply_suggestion_new_entry",
    "apply_suggestion_new_release",
    "catalog_suggestion_context",
    "list_suggestion_catalog_revisions",
    "revert_suggestion_catalog_target",
]