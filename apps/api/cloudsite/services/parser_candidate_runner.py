"""Shim: re-export from modules.automation.application.parser_candidate_runner.

Moved to modules/automation/application/ as part of C3 migration. This file
preserves the legacy import path for existing callers (routers/admin/*).
"""
from __future__ import annotations

from ..modules.automation.application.parser_candidate_runner import (  # noqa: F401
    ParserCandidateRunResult,
    parser_input_fingerprint,
    run_parser_candidate,
)

__all__ = [
    "ParserCandidateRunResult",
    "parser_input_fingerprint",
    "run_parser_candidate",
]
