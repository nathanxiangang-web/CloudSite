"""Shim: re-export from modules.automation.application.suggestion_review.

Moved to modules/automation/application/ as part of C3 migration. This file
preserves the legacy import path for existing callers (routers/admin/*).
"""
from __future__ import annotations

from ..modules.automation.application.suggestion_review import (  # noqa: F401
    ApplyResult,
    BatchApplyResult,
    SuggestionError,
    SuggestionNotFound,
    SuggestionStateInvalid,
    apply_suggestion,
    batch_apply_suggestions,
    batch_reject_suggestions,
    get_suggestion,
    list_suggestion_revisions,
    list_suggestions,
    reject_suggestion,
    revert_suggestion,
)

__all__ = [
    "ApplyResult",
    "BatchApplyResult",
    "SuggestionError",
    "SuggestionNotFound",
    "SuggestionStateInvalid",
    "apply_suggestion",
    "batch_apply_suggestions",
    "batch_reject_suggestions",
    "get_suggestion",
    "list_suggestion_revisions",
    "list_suggestions",
    "reject_suggestion",
    "revert_suggestion",
]
