"""Identity ORM ownership compatibility tests."""

from cloudsite.models import (
    FolderIdentity as LegacyFolderIdentity,
    FolderIdentityHistory as LegacyFolderIdentityHistory,
    ResourceIdentity as LegacyResourceIdentity,
    ResourceIdentityCandidate as LegacyResourceIdentityCandidate,
    ResourceIdentityHistory as LegacyResourceIdentityHistory,
)
from cloudsite.modules.identity.infrastructure.models import (
    FolderIdentity,
    FolderIdentityHistory,
    ResourceIdentity,
    ResourceIdentityCandidate,
    ResourceIdentityHistory,
)
from cloudsite.platform.db import IndexBase, StateBase


def test_legacy_identity_orm_exports_are_exact_module_classes():
    assert LegacyResourceIdentity is ResourceIdentity
    assert LegacyResourceIdentityHistory is ResourceIdentityHistory
    assert LegacyResourceIdentityCandidate is ResourceIdentityCandidate
    assert LegacyFolderIdentity is FolderIdentity
    assert LegacyFolderIdentityHistory is FolderIdentityHistory


def test_identity_orm_classes_are_owned_by_identity_infrastructure():
    classes = (
        ResourceIdentity,
        ResourceIdentityHistory,
        ResourceIdentityCandidate,
        FolderIdentity,
        FolderIdentityHistory,
    )
    assert all(
        cls.__module__ == "cloudsite.modules.identity.infrastructure.models"
        for cls in classes
    )


def test_identity_tables_remain_registered_on_shared_metadata():
    assert "resource_identities" in StateBase.metadata.tables
    assert "resource_identity_history" in StateBase.metadata.tables
    assert "folder_identities" in StateBase.metadata.tables
    assert "folder_identity_histories" in StateBase.metadata.tables
    assert "resource_identity_candidates" in IndexBase.metadata.tables


def test_identity_table_names_are_unchanged():
    assert ResourceIdentity.__tablename__ == "resource_identities"
    assert ResourceIdentityHistory.__tablename__ == "resource_identity_history"
    assert ResourceIdentityCandidate.__tablename__ == "resource_identity_candidates"
    assert FolderIdentity.__tablename__ == "folder_identities"
    assert FolderIdentityHistory.__tablename__ == "folder_identity_histories"
