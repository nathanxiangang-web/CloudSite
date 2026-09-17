"""Shim: re-export from modules.automation.application.parser_evaluation.

Moved to modules/automation/application/ as part of C3 migration. This file
preserves the legacy import path for existing callers (routers/admin/*).
"""
from __future__ import annotations

from ..modules.automation.application.parser_evaluation import (  # noqa: F401
    EVALUATED_FIELDS,
    ParserEvaluationCase,
    evaluate_parser_cases,
)

__all__ = [
    "EVALUATED_FIELDS",
    "ParserEvaluationCase",
    "evaluate_parser_cases",
]
