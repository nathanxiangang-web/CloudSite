"""Automation suggestion ORM ownership compatibility tests."""

from sqlalchemy import CheckConstraint, UniqueConstraint

from cloudsite.models import CatalogSuggestion as LegacyCatalogSuggestion
from cloudsite.modules.automation.infrastructure.models import CatalogSuggestion
from cloudsite.platform.db import StateBase


def test_legacy_catalog_suggestion_export_is_exact_module_class():
    assert LegacyCatalogSuggestion is CatalogSuggestion


def test_catalog_suggestion_orm_is_automation_owned():
    assert CatalogSuggestion.__module__ == (
        "cloudsite.modules.automation.infrastructure.models"
    )
    assert CatalogSuggestion.__tablename__ == "catalog_suggestions"
    assert "catalog_suggestions" in StateBase.metadata.tables


def test_catalog_suggestion_constraints_are_preserved():
    table = CatalogSuggestion.__table__

    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert (
        "source_file_id",
        "file_fingerprint",
        "parser_version",
        "suggestion_kind",
    ) in unique_columns

    checks = {
        str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert any(
        "new_entry" in sql
        and "new_release" in sql
        and "candidate_duplicate" in sql
        and "conflict" in sql
        for sql in checks
    )
    assert any(
        "pending" in sql
        and "reviewed" in sql
        and "applied" in sql
        and "rejected" in sql
        for sql in checks
    )
