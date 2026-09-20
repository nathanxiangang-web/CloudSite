"""Regression tests for Automation suggestion ownership and contracts."""

from cloudsite.models import CatalogSuggestion as LegacyCatalogSuggestion
from cloudsite.modules.automation.infrastructure.models import CatalogSuggestion
from cloudsite.platform.db import StateBase


def test_legacy_catalog_suggestion_export_is_exact_automation_class():
    assert LegacyCatalogSuggestion is CatalogSuggestion
    assert CatalogSuggestion.__module__ == (
        "cloudsite.modules.automation.infrastructure.models"
    )
    assert CatalogSuggestion.__tablename__ == "catalog_suggestions"
    assert "catalog_suggestions" in StateBase.metadata.tables
