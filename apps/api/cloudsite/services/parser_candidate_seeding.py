"""Shim: re-export from modules.automation.application.parser_candidate_seeding.

Moved to modules/automation/application/ as part of C3 migration. This file
preserves the legacy import path for existing callers (routers/admin/*).
"""
from __future__ import annotations

from ..modules.automation.application.parser_candidate_seeding import (  # noqa: F401
    MAX_SEED_ITEMS,
    ParserCandidateSeedResult,
    seed_parser_candidates_from_sync_run,
)
from ..modules.automation.application.parser_candidate_batch import (  # noqa: F401
    enqueue_indexed_resource,
)

__all__ = [
    "MAX_SEED_ITEMS",
    "ParserCandidateSeedResult",
    "seed_parser_candidates_from_sync_run",
    "enqueue_indexed_resource",
]
