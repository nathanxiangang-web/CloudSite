"""Catalog ORM ownership compatibility tests."""

from cloudsite.models import (
    CatalogAsset as LegacyCatalogAsset,
    CatalogEntry as LegacyCatalogEntry,
    CatalogFavorite as LegacyCatalogFavorite,
    CatalogLocation as LegacyCatalogLocation,
    CatalogRelation as LegacyCatalogRelation,
    CatalogRelease as LegacyCatalogRelease,
    CatalogReleaseNotification as LegacyCatalogReleaseNotification,
    CatalogRevision as LegacyCatalogRevision,
    CatalogSearchOutbox as LegacyCatalogSearchOutbox,
    CatalogSubscription as LegacyCatalogSubscription,
    CatalogTag as LegacyCatalogTag,
    CatalogTagAssignment as LegacyCatalogTagAssignment,
)
from cloudsite.modules.catalog.infrastructure.models import (
    CatalogAsset,
    CatalogEntry,
    CatalogFavorite,
    CatalogLocation,
    CatalogRelation,
    CatalogRelease,
    CatalogReleaseNotification,
    CatalogRevision,
    CatalogSearchOutbox,
    CatalogSubscription,
    CatalogTag,
    CatalogTagAssignment,
)
from cloudsite.platform.db import StateBase


CATALOG_MODELS = (
    CatalogEntry,
    CatalogRelease,
    CatalogAsset,
    CatalogLocation,
    CatalogTag,
    CatalogTagAssignment,
    CatalogRelation,
    CatalogRevision,
    CatalogSearchOutbox,
    CatalogFavorite,
    CatalogSubscription,
    CatalogReleaseNotification,
)


def test_legacy_catalog_exports_are_exact_module_classes():
    assert LegacyCatalogEntry is CatalogEntry
    assert LegacyCatalogRelease is CatalogRelease
    assert LegacyCatalogAsset is CatalogAsset
    assert LegacyCatalogLocation is CatalogLocation
    assert LegacyCatalogTag is CatalogTag
    assert LegacyCatalogTagAssignment is CatalogTagAssignment
    assert LegacyCatalogRelation is CatalogRelation
    assert LegacyCatalogRevision is CatalogRevision
    assert LegacyCatalogSearchOutbox is CatalogSearchOutbox
    assert LegacyCatalogFavorite is CatalogFavorite
    assert LegacyCatalogSubscription is CatalogSubscription
    assert LegacyCatalogReleaseNotification is CatalogReleaseNotification


def test_catalog_orm_classes_are_owned_by_catalog_infrastructure():
    assert all(
        cls.__module__ == "cloudsite.modules.catalog.infrastructure.models"
        for cls in CATALOG_MODELS
    )


def test_catalog_owned_tables_remain_registered_on_state_metadata():
    expected = {
        "catalog_entries",
        "catalog_releases",
        "catalog_assets",
        "catalog_locations",
        "catalog_tags",
        "catalog_tag_assignments",
        "catalog_relations",
        "catalog_revisions",
        "catalog_search_outbox",
        "catalog_favorites",
        "catalog_subscriptions",
        "catalog_release_notifications",
    }
    assert expected <= set(StateBase.metadata.tables)


def test_catalog_table_names_are_unchanged():
    assert {cls.__tablename__ for cls in CATALOG_MODELS} == {
        "catalog_entries",
        "catalog_releases",
        "catalog_assets",
        "catalog_locations",
        "catalog_tags",
        "catalog_tag_assignments",
        "catalog_relations",
        "catalog_revisions",
        "catalog_search_outbox",
        "catalog_favorites",
        "catalog_subscriptions",
        "catalog_release_notifications",
    }
