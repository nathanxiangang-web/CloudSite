"""Automation parser ownership compatibility tests."""

from sqlalchemy import CheckConstraint, UniqueConstraint

from cloudsite.models import ParserCandidateTask as LegacyParserCandidateTask
from cloudsite.modules.automation.domain import resource_name_parser as parser_domain
from cloudsite.modules.automation.infrastructure.models import ParserCandidateTask
from cloudsite.platform.db import StateBase
from cloudsite.services import resource_name_parser as legacy_parser


def test_legacy_parser_candidate_export_is_exact_module_class():
    assert LegacyParserCandidateTask is ParserCandidateTask


def test_parser_candidate_orm_is_automation_owned():
    assert ParserCandidateTask.__module__ == (
        "cloudsite.modules.automation.infrastructure.models"
    )
    assert ParserCandidateTask.__tablename__ == "parser_candidate_tasks"
    assert "parser_candidate_tasks" in StateBase.metadata.tables


def test_parser_candidate_constraints_are_preserved():
    table = ParserCandidateTask.__table__

    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert (
        "resource_id",
        "input_fingerprint",
        "parser_version",
    ) in unique_columns

    checks = {
        str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert any(
        "pending" in sql
        and "running" in sql
        and "completed" in sql
        and "failed" in sql
        and "cancelled" in sql
        for sql in checks
    )


def test_legacy_parser_service_is_exact_domain_facade():
    assert legacy_parser.PARSER_VERSION == parser_domain.PARSER_VERSION
    assert legacy_parser.UNKNOWN == parser_domain.UNKNOWN
    assert legacy_parser.Evidence is parser_domain.Evidence
    assert legacy_parser.ParseResult is parser_domain.ParseResult
    assert legacy_parser.parse_resource_name is parser_domain.parse_resource_name
