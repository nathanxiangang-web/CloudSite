"""Bounded batch coordinator for durable A1 parser candidate tasks.

Connects indexed resource events to the durable parser-candidate queue and
processes a bounded batch in shadow mode without committing either database
session or mutating formal Catalog content.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import ParserCandidateTask, Resource
from .parser_candidate_runner import (
    ParserCandidateRunResult,
    parser_input_fingerprint,
    run_parser_candidate,
)
from .parser_candidates import (
    ParserCandidateError,
    enqueue_parser_candidate,
    fail_parser_candidate,
)
from ....services.resource_name_parser import PARSER_VERSION

INTERRUPTED_MESSAGE = "parser candidate interrupted by restart"

_DEFAULT_LIST_LIMIT = 100
_MAX_LIST_LIMIT = 500
_CANDIDATE_STATUSES = frozenset({"pending", "running", "completed", "failed", "cancelled"})


@dataclass(frozen=True)
class ParserCandidateBatchResult:
    """Outcome of a bounded batch run.

    Attributes:
        outcomes: One entry per attempted candidate, in execution order.
        attempted: Number of candidates actually run (len(outcomes)).
        stopped_reason: Why the batch stopped -- "max_items", "time_budget",
            or "exhausted" (no more pending candidates).
    """

    outcomes: tuple[ParserCandidateRunResult, ...]
    attempted: int
    stopped_reason: str


async def enqueue_indexed_resource(
    state: AsyncSession,
    index: AsyncSession,
    resource_id: str,
) -> tuple[ParserCandidateTask, bool]:
    """Enqueue one active indexed resource using the exact parser-input fingerprint.

    Repeated unchanged input is idempotent (returns the existing row with
    created=False). Changed parser input (different name, path, extension, or
    mime_type) produces a new fingerprint and creates a new candidate. The
    state session is flushed but not committed.
    """

    resource = await index.get(Resource, resource_id)
    if resource is None or resource.status != "active":
        raise ParserCandidateError("indexed resource is unavailable or inactive")
    fingerprint = parser_input_fingerprint(resource)
    return await enqueue_parser_candidate(
        state,
        resource_id=resource.id,
        input_fingerprint=fingerprint,
        parser_version=PARSER_VERSION,
    )


async def list_parser_candidates(
    state: AsyncSession,
    *,
    status: str | None = None,
    resource_id: str | None = None,
    limit: int = _DEFAULT_LIST_LIMIT,
    offset: int = 0,
) -> list[ParserCandidateTask]:
    """Return candidates in creation order with optional filters and bounds.

    Ordering is by created_at then task_id to keep a deterministic total order
    even when multiple rows share the same timestamp.
    """

    if status is not None and status not in _CANDIDATE_STATUSES:
        raise ParserCandidateError("invalid parser candidate status")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= _MAX_LIST_LIMIT:
        raise ParserCandidateError(f"limit must be between 1 and {_MAX_LIST_LIMIT}")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise ParserCandidateError("offset must be a non-negative integer")

    query = select(ParserCandidateTask).order_by(
        ParserCandidateTask.created_at, ParserCandidateTask.task_id
    )
    if status is not None:
        query = query.where(ParserCandidateTask.status == status)
    if resource_id is not None:
        query = query.where(ParserCandidateTask.resource_id == resource_id)
    query = query.offset(offset).limit(limit)
    return list((await state.scalars(query)).all())


async def run_parser_candidate_batch(
    state: AsyncSession,
    index: AsyncSession,
    *,
    max_items: int,
    time_budget_seconds: float,
) -> ParserCandidateBatchResult:
    """Run pending candidates in creation order up to item and time bounds.

    Uses the existing exact-input runner. One failed item does not block later
    items: expected failures are recorded as outcomes and the batch continues.
    Neither database session is committed inside this function.

    The time budget is checked before each candidate. A budget of zero or less
    stops the batch immediately without running any candidates.
    """

    if max_items <= 0:
        return ParserCandidateBatchResult(
            outcomes=(), attempted=0, stopped_reason="max_items"
        )
    start = time.monotonic()
    outcomes: list[ParserCandidateRunResult] = []
    while len(outcomes) < max_items:
        elapsed = time.monotonic() - start
        if elapsed >= time_budget_seconds:
            return ParserCandidateBatchResult(
                outcomes=tuple(outcomes),
                attempted=len(outcomes),
                stopped_reason="time_budget",
            )
        row = await state.scalar(
            select(ParserCandidateTask)
            .where(ParserCandidateTask.status == "pending")
            .order_by(ParserCandidateTask.created_at, ParserCandidateTask.task_id)
            .limit(1)
        )
        if row is None:
            return ParserCandidateBatchResult(
                outcomes=tuple(outcomes),
                attempted=len(outcomes),
                stopped_reason="exhausted",
            )
        try:
            outcome = await run_parser_candidate(state, index, row.task_id)
        except ParserCandidateError as exc:
            refreshed = await state.get(ParserCandidateTask, row.task_id)
            outcome = ParserCandidateRunResult(
                task=refreshed if refreshed is not None else row,
                result=None,
                error=str(exc),
            )
        outcomes.append(outcome)
    return ParserCandidateBatchResult(
        outcomes=tuple(outcomes),
        attempted=len(outcomes),
        stopped_reason="max_items",
    )


async def recover_interrupted_candidates(
    state: AsyncSession,
    limit: int = 1000,
) -> list[ParserCandidateTask]:
    """Convert leftover running candidates to failed with an interrupted message.

    After an unexpected restart, previously running tasks cannot be resumed
    in-place. This marks them as failed so they can use the existing explicit
    retry operation. The database session is not committed inside this function.
    """

    rows = list(
        (
            await state.scalars(
                select(ParserCandidateTask).where(
                    ParserCandidateTask.status == "running"
                )
            )
        ).all()
    )
    recovered: list[ParserCandidateTask] = []
    for row in rows:
        recovered.append(
            await fail_parser_candidate(state, row.task_id, INTERRUPTED_MESSAGE)
        )
    return recovered
