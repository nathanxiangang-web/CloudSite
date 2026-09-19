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
    "CatalogError",
    "CatalogEntryNotFound",
    "CatalogReleaseNotFound",
    "CatalogAssetNotFound",
    "CatalogRevisionConflict",
    "CatalogSlugConflict",
    "CatalogLocationInvalid",
    "CatalogPublishValidationFailed",
    "CatalogAssetNotDownloadable",
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
]
