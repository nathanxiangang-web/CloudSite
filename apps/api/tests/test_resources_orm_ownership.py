"""Resources ORM ownership compatibility tests."""

from cloudsite.models import (
    DownloadRateLimit as LegacyDownloadRateLimit,
    Folder as LegacyFolder,
    Resource as LegacyResource,
)
from cloudsite.modules.resources.infrastructure.models import DownloadRateLimit, Folder, Resource
from cloudsite.platform.db import IndexBase, StateBase


def test_legacy_resources_orm_exports_are_exact_module_classes():
    assert LegacyDownloadRateLimit is DownloadRateLimit
    assert LegacyFolder is Folder
    assert LegacyResource is Resource


def test_resources_orm_classes_are_owned_by_resources_infrastructure():
    assert all(
        cls.__module__ == "cloudsite.modules.resources.infrastructure.models"
        for cls in (DownloadRateLimit, Folder, Resource)
    )


def test_resources_tables_remain_registered_on_shared_metadata():
    assert "download_rate_limits" in StateBase.metadata.tables
    assert "folders" in IndexBase.metadata.tables
    assert "resources" in IndexBase.metadata.tables


def test_resources_table_names_are_unchanged():
    assert DownloadRateLimit.__tablename__ == "download_rate_limits"
    assert Folder.__tablename__ == "folders"
    assert Resource.__tablename__ == "resources"


def test_resource_path_uniqueness_constraints_are_preserved():
    folder_constraints = {
        tuple(column.name for column in constraint.columns)
        for constraint in Folder.__table__.constraints
        if hasattr(constraint, "columns")
    }
    resource_constraints = {
        tuple(column.name for column in constraint.columns)
        for constraint in Resource.__table__.constraints
        if hasattr(constraint, "columns")
    }
    assert ("root_mapping_id", "path") in folder_constraints
    assert ("root_mapping_id", "path") in resource_constraints
