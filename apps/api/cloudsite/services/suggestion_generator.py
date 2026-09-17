"""Shim: re-export from modules.automation.application.suggestion_generator.

Moved to modules/automation/application/ as part of C3 migration. This file
preserves the legacy import path for existing callers (routers/admin/*).
"""
from __future__ import annotations

from ..modules.automation.application.suggestion_generator import (  # noqa: F401
    ALL_KINDS,
    SUGGESTION_ID_PREFIX,
    GenerationResult,
    _slugify,
    compute_file_fingerprint,
    generate_suggestions_batch,
    generate_suggestions_for_resource,
)

__all__ = [
    "ALL_KINDS",
    "SUGGESTION_ID_PREFIX",
    "GenerationResult",
    "_slugify",
    "compute_file_fingerprint",
    "generate_suggestions_batch",
    "generate_suggestions_for_resource",
]
