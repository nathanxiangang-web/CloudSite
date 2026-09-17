"""Shim: re-export from modules.automation.application.parser_candidates.

Moved to modules/automation/application/ as part of C3 migration. This file
preserves the legacy import path for existing callers (routers/admin/*).
"""
from __future__ import annotations

from ..modules.automation.application.parser_candidates import (  # noqa: F401
    DEFAULT_MAX_RETRIES,
    TASK_ID_PREFIX,
    ParserCandidateError,
    ParserCandidateNotFound,
    ParserCandidateTransitionInvalid,
    cancel_parser_candidate,
    claim_parser_candidate,
    complete_parser_candidate,
    enqueue_parser_candidate,
    fail_parser_candidate,
    get_parser_candidate,
    retry_parser_candidate,
)

__all__ = [
    "DEFAULT_MAX_RETRIES",
    "TASK_ID_PREFIX",
    "ParserCandidateError",
    "ParserCandidateNotFound",
    "ParserCandidateTransitionInvalid",
    "cancel_parser_candidate",
    "claim_parser_candidate",
    "complete_parser_candidate",
    "enqueue_parser_candidate",
    "fail_parser_candidate",
    "get_parser_candidate",
    "retry_parser_candidate",
]
