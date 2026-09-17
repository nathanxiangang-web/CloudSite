"""Shim: re-export from modules.automation.application.parser_candidate_batch.

Moved to modules/automation/application/ as part of C3 migration. This file
preserves the legacy import path for existing callers (routers/admin/*).
"""
from __future__ import annotations

from ..modules.automation.application.parser_candidate_batch import (  # noqa: F401
    INTERRUPTED_MESSAGE,
    ParserCandidateBatchResult,
    enqueue_indexed_resource,
    list_parser_candidates,
    recover_interrupted_candidates,
    run_parser_candidate_batch,
)

__all__ = [
    "INTERRUPTED_MESSAGE",
    "ParserCandidateBatchResult",
    "enqueue_indexed_resource",
    "list_parser_candidates",
    "recover_interrupted_candidates",
    "run_parser_candidate_batch",
]
