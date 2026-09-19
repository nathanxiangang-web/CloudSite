"""Stable public contract for the Catalog module."""

from __future__ import annotations

from ..application.automation_facade import (
    CatalogAutomationApplyResult,
    CatalogAutomationContext,
    CatalogDuplicateView,
    CatalogRevisionView,
    apply_automation_asset,
    apply_automation_new_entry,
    apply_automation_new_release,
    catalog_automation_context,
    find_catalog_duplicate_asset,
    list_automation_revisions,
    revert_automation_target,
)
from ..application.browse_facade import (
    BrowseCatalogEntryView,
    published_browse_entries,
)
from ..application.collection_facade import (
    CatalogCollectionEntryView,
    collection_entry_references,
)
from ..application.catalog_entry import (
    count_catalog_entries,
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

from ..application.publication_scope import (
    CatalogPublicationNotFound,
    CatalogPublicationNotPublic,
    list_publication_scope_entries,
    public_catalog_entry,
    update_publication_scope,
)
from ..application.public_queries import (
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
    "CatalogError",
    "CatalogEntryNotFound",
    "CatalogReleaseNotFound",
    "CatalogAssetNotFound",
    "CatalogRevisionConflict",
    "CatalogSlugConflict",
    "CatalogLocationInvalid",
    "CatalogPublishValidationFailed",
    "CatalogAssetNotDownloadable",
    "count_catalog_entries",
    "CreateCatalogEntryResult",
    "CreateCatalogReleaseResult",
    "CreateCatalogAssetResult",
    "LocationResolution",
    "AttachCatalogLocationResult",
    "PreviewValidationResult",
    "PublishCatalogEntryResult",
    "AssetDownloadTarget",
    "CatalogAutomationApplyResult",
    "CatalogAutomationContext",
    "CatalogDuplicateView",
    "CatalogRevisionView",
    "catalog_automation_context",
    "find_catalog_duplicate_asset",
    "apply_automation_new_entry",
    "apply_automation_new_release",
    "apply_automation_asset",
    "revert_automation_target",
    "list_automation_revisions",
    "CatalogViewNotFound",
    "catalog_asset_view",
    "catalog_entry_view",
    "catalog_release_view",
    "published_catalog_page",
    "public_catalog_entry_view",
    "public_catalog_release_view",
    "public_catalog_asset_view",
    "CatalogCollectionEntryView",
    "collection_entry_references",
    "BrowseCatalogEntryView",
    "published_browse_entries",
    "CatalogPublicationNotFound",
    "CatalogPublicationNotPublic",
    "list_publication_scope_entries",
    "public_catalog_entry",
    "update_publication_scope",
]

