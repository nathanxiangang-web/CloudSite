"""Automation module public API.

Re-exports the application-layer surface as the stable public contract of the
automation module. External consumers should import from
``modules.automation.contracts.public`` rather than reaching into
``application`` directly.

These symbols were relocated from ``services/`` as part of the C3 migration;
the legacy ``services/*`` files now re-export the same symbols through shims.
"""
from __future__ import annotations

from ..application.parser_candidate_batch import (
    INTERRUPTED_MESSAGE,
    ParserCandidateBatchResult,
    enqueue_indexed_resource,
    list_parser_candidates,
    recover_interrupted_candidates,
    run_parser_candidate_batch,
)
from ..application.parser_candidate_runner import (
    ParserCandidateRunResult,
    parser_input_fingerprint,
    run_parser_candidate,
)
from ..application.parser_candidate_seeding import (
    MAX_SEED_ITEMS,
    ParserCandidateSeedResult,
    seed_parser_candidates_from_sync_run,
)
from ..application.parser_candidates import (
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
from ..application.parser_evaluation import (
    EVALUATED_FIELDS,
    ParserEvaluationCase,
    evaluate_parser_cases,
)
from ..application.suggestion_generator import (
    ALL_KINDS,
    SUGGESTION_ID_PREFIX,
    GenerationResult,
    compute_file_fingerprint,
    generate_suggestions_batch,
    generate_suggestions_for_resource,
)
from ..application.suggestion_review import (
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
    # suggestion_generator
    "ALL_KINDS",
    "SUGGESTION_ID_PREFIX",
    "GenerationResult",
    "compute_file_fingerprint",
    "generate_suggestions_batch",
    "generate_suggestions_for_resource",
    # suggestion_review
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
    # parser_candidates
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
    # parser_candidate_runner
    "ParserCandidateRunResult",
    "parser_input_fingerprint",
    "run_parser_candidate",
    # parser_candidate_batch
    "INTERRUPTED_MESSAGE",
    "ParserCandidateBatchResult",
    "enqueue_indexed_resource",
    "list_parser_candidates",
    "recover_interrupted_candidates",
    "run_parser_candidate_batch",
    # parser_candidate_seeding
    "MAX_SEED_ITEMS",
    "ParserCandidateSeedResult",
    "seed_parser_candidates_from_sync_run",
    # parser_evaluation
    "EVALUATED_FIELDS",
    "ParserEvaluationCase",
    "evaluate_parser_cases",
]