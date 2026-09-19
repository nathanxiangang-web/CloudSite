"""Providers ORM ownership compatibility tests."""

from cloudsite.models import (
    AListConnection as LegacyAListConnection,
    ContentRootMapping as LegacyContentRootMapping,
    ProviderSyncState as LegacyProviderSyncState,
)
from cloudsite.modules.providers.infrastructure.models import (
    AListConnection,
    ContentRootMapping,
    ProviderSyncState,
)
from cloudsite.platform.db import IndexBase, StateBase


def test_legacy_provider_orm_exports_are_exact_module_classes():
    assert LegacyAListConnection is AListConnection
    assert LegacyContentRootMapping is ContentRootMapping
    assert LegacyProviderSyncState is ProviderSyncState


def test_provider_orm_classes_are_owned_by_providers_infrastructure():
    assert all(
        cls.__module__ == "cloudsite.modules.providers.infrastructure.models"
        for cls in (AListConnection, ContentRootMapping, ProviderSyncState)
    )


def test_provider_tables_remain_registered_on_shared_metadata():
    assert "alist_connections" in StateBase.metadata.tables
    assert "content_root_mappings" in StateBase.metadata.tables
    assert "provider_sync_state" in IndexBase.metadata.tables


def test_provider_table_names_are_unchanged():
    assert AListConnection.__tablename__ == "alist_connections"
    assert ContentRootMapping.__tablename__ == "content_root_mappings"
    assert ProviderSyncState.__tablename__ == "provider_sync_state"


def test_provider_uniqueness_constraints_are_preserved():
    root_constraints = {
        tuple(column.name for column in constraint.columns)
        for constraint in ContentRootMapping.__table__.constraints
        if hasattr(constraint, "columns")
    }
    sync_constraints = {
        tuple(column.name for column in constraint.columns)
        for constraint in ProviderSyncState.__table__.constraints
        if hasattr(constraint, "columns")
    }
    assert ("connection_id", "alist_path") in root_constraints
    assert ("connection_id", "root_mapping_id") in sync_constraints
