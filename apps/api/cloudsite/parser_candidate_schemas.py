"""Strict request and response schemas for the administrator parser candidate API.

These models form the typed HTTP boundary for inspecting and exercising the
durable shadow parser-candidate queue. They never carry enough information to
overwrite formal Catalog content; they only describe candidate tasks, bounded
batch execution, retry, and restart recovery.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ---- Shared field patterns ----

_TASK_ID_PATTERN = r"^pt_[0-9a-f]{32}$"
_RESOURCE_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
_FINGERPRINT_PATTERN = r"^[0-9a-f]{64}$"

_CANDIDATE_STATUS = Literal["pending", "running", "completed", "failed", "cancelled"]
_BATCH_STOPPED_REASON = Literal["max_items", "time_budget", "exhausted"]

# Bounds mirrored from services.parser_candidate_batch to keep the HTTP
# boundary fail-closed before reaching the service layer.
MAX_LIST_LIMIT = 500
DEFAULT_LIST_LIMIT = 100
MAX_BATCH_ITEMS = 500
MAX_TIME_BUDGET_SECONDS = 3600.0
MAX_RETRY_LIMIT = 20


# ---- Request schemas ----


class ParserCandidateEnqueueInput(BaseModel):
    """Enqueue one active indexed resource into the shadow candidate queue."""

    model_config = ConfigDict(extra="forbid")

    resource_id: str = Field(pattern=_RESOURCE_ID_PATTERN)


class ParserCandidateBatchInput(BaseModel):
    """Run a bounded batch of pending candidates in shadow mode.

    Neither database session is committed inside the batch service; the route
    commits only on success. A zero time budget stops immediately without
    running any candidates.
    """

    model_config = ConfigDict(extra="forbid")

    max_items: int = Field(ge=1, le=MAX_BATCH_ITEMS)
    time_budget_seconds: float = Field(ge=0.0, le=MAX_TIME_BUDGET_SECONDS)


class ParserCandidateRetryInput(BaseModel):
    """Retry one failed candidate task by resetting it to pending.

    The retry count is incremented; when it reaches max_retries the service
    rejects further retries with a transition conflict.
    """

    model_config = ConfigDict(extra="forbid")

    max_retries: int = Field(default=3, ge=1, le=MAX_RETRY_LIMIT)


# ---- Response schemas ----


class ParserCandidateTaskOutput(BaseModel):
    """Serializable view of a durable parser candidate task.

    result_json carries the parser evidence JSON for completed tasks; it is
    never interpreted by the HTTP layer and never overwrites Catalog fields.
    """

    model_config = ConfigDict(from_attributes=True)

    task_id: str
    resource_id: str
    input_fingerprint: str
    parser_version: str
    status: _CANDIDATE_STATUS
    retry_count: int
    result_json: str | None = None
    error_text: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class ParserCandidateListOutput(BaseModel):
    """Paginated candidate listing with the applied filter context."""

    items: list[ParserCandidateTaskOutput]
    status: str | None = None
    resource_id: str | None = None
    limit: int
    offset: int
    total_returned: int


class ParserCandidateEnqueueOutput(BaseModel):
    """Outcome of enqueueing one indexed resource.

    created is False when the exact input fingerprint already had a candidate
    (idempotent); created is True when a new candidate was inserted.
    """

    task: ParserCandidateTaskOutput
    created: bool


class ParserCandidateBatchOutcomeOutput(BaseModel):
    """One candidate outcome inside a bounded batch run."""

    task: ParserCandidateTaskOutput
    result: dict | None = None
    error: str | None = None


class ParserCandidateBatchOutput(BaseModel):
    """Aggregated outcome of a bounded batch run.

    stopped_reason is "max_items", "time_budget", or "exhausted". Neither
    database session is committed inside the batch service; the route commits
    only on success.
    """

    outcomes: list[ParserCandidateBatchOutcomeOutput]
    attempted: int
    stopped_reason: _BATCH_STOPPED_REASON


class ParserCandidateRecoveryOutput(BaseModel):
    """Outcome of restart recovery for interrupted running candidates.

    Each previously running task is converted to failed with an interrupted
    message so it can use the existing explicit retry operation.
    """

    recovered: list[ParserCandidateTaskOutput]
    recovered_count: int


class ParserEvaluationExpected(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: str | None = Field(default=None, max_length=40)
    architecture: str | None = Field(default=None, max_length=40)
    language: str | None = Field(default=None, max_length=40)
    version: str | None = Field(default=None, max_length=80)
    package_form: str | None = Field(default=None, max_length=40)


class ParserEvaluationCaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_id: str = Field(pattern=_RESOURCE_ID_PATTERN)
    name: str = Field(min_length=1, max_length=500)
    path: str = Field(default="", max_length=2000)
    extension: str = Field(default="", max_length=40)
    mime_type: str = Field(default="", max_length=200)
    expected: ParserEvaluationExpected


class ParserEvaluationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cases: list[ParserEvaluationCaseInput] = Field(min_length=1, max_length=100)
