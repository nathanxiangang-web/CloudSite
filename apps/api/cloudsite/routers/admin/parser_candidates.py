"""Administrator routes for the durable shadow parser-candidate queue.

Exposes candidate listing, bounded batch execution, retry, and restart
recovery without modifying formal Catalog content. All operations are
shadow-only: parser results are stored on candidate rows, never published to
Catalog entries, releases, or assets.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query

from ...parser_candidate_schemas import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    ParserCandidateBatchInput,
    ParserCandidateBatchOutput,
    ParserCandidateBatchOutcomeOutput,
    ParserCandidateEnqueueInput,
    ParserCandidateEnqueueOutput,
    ParserCandidateListOutput,
    ParserCandidateRecoveryOutput,
    ParserCandidateRetryInput,
    ParserCandidateTaskOutput,
    ParserEvaluationInput,
)
from ...services.parser_candidates import (
    ParserCandidateError,
    ParserCandidateNotFound,
    ParserCandidateTransitionInvalid,
)
from ...services.resource_name_parser import ParseResult

router = APIRouter()

_CANDIDATE_STATUSES = frozenset(
    {"pending", "running", "completed", "failed", "cancelled"}
)


@router.post("/api/admin/parser-candidates/evaluate")
async def admin_evaluate_parser(payload: ParserEvaluationInput):
    """Evaluate a bounded fixture set without creating tasks or Catalog data."""
    from ...services.parser_evaluation import ParserEvaluationCase, evaluate_parser_cases

    cases = [
        ParserEvaluationCase(
            resource_id=item.resource_id,
            name=item.name,
            path=item.path,
            extension=item.extension,
            mime_type=item.mime_type,
            expected=item.expected.model_dump(exclude_none=True),
        )
        for item in payload.cases
    ]
    return evaluate_parser_cases(cases)


def _translate_candidate_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ParserCandidateNotFound):
        return HTTPException(
            404,
            {"code": "PARSER_CANDIDATE_NOT_FOUND", "message": "Parser candidate task not found"},
        )
    if isinstance(exc, ParserCandidateTransitionInvalid):
        return HTTPException(
            409,
            {"code": "PARSER_CANDIDATE_CONFLICT", "message": str(exc)},
        )
    return HTTPException(
        400,
        {"code": "PARSER_CANDIDATE_ERROR", "message": str(exc)},
    )


def _task_to_output(task) -> ParserCandidateTaskOutput:
    return ParserCandidateTaskOutput(
        task_id=task.task_id,
        resource_id=task.resource_id,
        input_fingerprint=task.input_fingerprint,
        parser_version=task.parser_version,
        status=task.status,
        retry_count=task.retry_count,
        result_json=task.result_json,
        error_text=task.error_text,
        created_at=task.created_at,
        updated_at=task.updated_at,
        completed_at=task.completed_at,
    )


@router.get(
    "/api/admin/parser-candidates",
    response_model=ParserCandidateListOutput,
)
async def admin_list_parser_candidates(
    status: str | None = Query(default=None),
    resource_id: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    """List durable parser candidates in creation order with filters and bounds.

    Ordering is by created_at then task_id for a deterministic total order.
    Invalid status or bounds are rejected before reaching the service layer.
    """
    from ...main import StateSession
    from ...services.parser_candidate_batch import list_parser_candidates

    if status is not None and status not in _CANDIDATE_STATUSES:
        raise HTTPException(
            400,
            {"code": "PARSER_CANDIDATE_INVALID_STATUS", "message": "invalid parser candidate status"},
        )

    async with StateSession() as state:
        try:
            rows = await list_parser_candidates(
                state,
                status=status,
                resource_id=resource_id,
                limit=limit,
                offset=offset,
            )
        except ParserCandidateError as exc:
            raise _translate_candidate_error(exc) from exc
        items = [_task_to_output(row) for row in rows]
        return ParserCandidateListOutput(
            items=items,
            status=status,
            resource_id=resource_id,
            limit=limit,
            offset=offset,
            total_returned=len(items),
        )


@router.post(
    "/api/admin/parser-candidates/enqueue",
    response_model=ParserCandidateEnqueueOutput,
    status_code=201,
)
async def admin_enqueue_parser_candidate(payload: ParserCandidateEnqueueInput):
    """Enqueue one active indexed resource using the exact parser-input fingerprint.

    Repeated unchanged input is idempotent (returns the existing row with
    created=False and HTTP 201). Changed parser input produces a new
    fingerprint and creates a new candidate. Only the state session is
    committed; the index session is read-only.
    """
    from ...main import IndexSession, StateSession
    from ...services.parser_candidate_batch import enqueue_indexed_resource

    async with StateSession() as state, IndexSession() as index:
        try:
            task, created = await enqueue_indexed_resource(
                state, index, payload.resource_id
            )
            await state.commit()
        except ParserCandidateError as exc:
            raise _translate_candidate_error(exc) from exc
        return ParserCandidateEnqueueOutput(
            task=_task_to_output(task),
            created=created,
        )


@router.post(
    "/api/admin/parser-candidates/batch",
    response_model=ParserCandidateBatchOutput,
)
async def admin_run_parser_candidate_batch(payload: ParserCandidateBatchInput):
    """Run a bounded batch of pending candidates in shadow mode.

    One failed item does not block later items. Neither database session is
    committed inside the batch service; the route commits the state session
    only on success. The index session is read-only for resource lookups.
    """
    from ...main import IndexSession, StateSession
    from ...services.parser_candidate_batch import run_parser_candidate_batch

    async with StateSession() as state, IndexSession() as index:
        try:
            result = await run_parser_candidate_batch(
                state,
                index,
                max_items=payload.max_items,
                time_budget_seconds=payload.time_budget_seconds,
            )
            await state.commit()
        except ParserCandidateError as exc:
            raise _translate_candidate_error(exc) from exc
        outcomes: list[ParserCandidateBatchOutcomeOutput] = []
        for outcome in result.outcomes:
            parsed_result: dict | None = None
            if outcome.result is not None:
                try:
                    parsed_result = json.loads(outcome.task.result_json or "{}")
                except (json.JSONDecodeError, TypeError):
                    parsed_result = None
            outcomes.append(
                ParserCandidateBatchOutcomeOutput(
                    task=_task_to_output(outcome.task),
                    result=parsed_result,
                    error=outcome.error,
                )
            )
        return ParserCandidateBatchOutput(
            outcomes=outcomes,
            attempted=result.attempted,
            stopped_reason=result.stopped_reason,
        )


@router.post(
    "/api/admin/parser-candidates/{task_id}/retry",
    response_model=ParserCandidateTaskOutput,
)
async def admin_retry_parser_candidate(
    task_id: str,
    payload: ParserCandidateRetryInput,
):
    """Retry one failed candidate task by resetting it to pending.

    The retry count is incremented; when it reaches max_retries the service
    rejects further retries with a 409 conflict. Only the state session is
    committed.
    """
    from ...main import StateSession
    from ...services.parser_candidates import retry_parser_candidate

    async with StateSession() as state:
        try:
            task = await retry_parser_candidate(
                state, task_id, max_retries=payload.max_retries
            )
            await state.commit()
        except ParserCandidateError as exc:
            raise _translate_candidate_error(exc) from exc
        return _task_to_output(task)


@router.post(
    "/api/admin/parser-candidates/recover",
    response_model=ParserCandidateRecoveryOutput,
)
async def admin_recover_interrupted_candidates():
    """Recover interrupted running candidates after an unexpected restart.

    Previously running tasks cannot be resumed in-place; they are converted to
    failed with an interrupted message so they can use the existing explicit
    retry operation. Only the state session is committed.
    """
    from ...main import StateSession
    from ...services.parser_candidate_batch import recover_interrupted_candidates

    async with StateSession() as state:
        try:
            recovered = await recover_interrupted_candidates(state)
            await state.commit()
        except ParserCandidateError as exc:
            raise _translate_candidate_error(exc) from exc
        items = [_task_to_output(row) for row in recovered]
        return ParserCandidateRecoveryOutput(
            recovered=items,
            recovered_count=len(items),
        )



@router.get(
    "/api/admin/parser-candidates/{task_id}",
    response_model=ParserCandidateTaskOutput,
)
async def admin_get_parser_candidate(task_id: str):
    """Get a single parser candidate task by ID."""
    from ...main import StateSession
    from ...services.parser_candidates import get_parser_candidate

    async with StateSession() as state:
        try:
            task = await get_parser_candidate(state, task_id)
        except ParserCandidateError as exc:
            raise _translate_candidate_error(exc) from exc
        return _task_to_output(task)


@router.post(
    "/api/admin/parser-candidates/{task_id}/cancel",
    response_model=ParserCandidateTaskOutput,
)
async def admin_cancel_parser_candidate(task_id: str):
    """Cancel a pending or running parser candidate task."""
    from ...main import StateSession
    from ...services.parser_candidates import cancel_parser_candidate

    async with StateSession() as state:
        try:
            task = await cancel_parser_candidate(state, task_id)
            await state.commit()
        except ParserCandidateError as exc:
            raise _translate_candidate_error(exc) from exc
        return _task_to_output(task)


@router.post(
    "/api/admin/parser-candidates/seed",
    response_model=ParserCandidateEnqueueOutput,
)
async def admin_seed_parser_candidates_from_sync(
    sync_run_id: int,
    max_items: int = Query(500, ge=1, le=5000),
):
    """Seed parser candidates from a completed sync run.

    Scans resources changed in the given sync run and enqueues
    parser candidate tasks for each, skipping those already enqueued.
    """
    from ...main import StateSession, IndexSession
    from ...services.parser_candidate_seeding import seed_parser_candidates_from_sync_run

    async with StateSession() as state, IndexSession() as index:
        try:
            result = await seed_parser_candidates_from_sync_run(
                state, index, sync_run_id=sync_run_id, max_items=max_items,
            )
            await state.commit()
        except ParserCandidateError as exc:
            raise _translate_candidate_error(exc) from exc
        return ParserCandidateEnqueueOutput(
            enqueued_count=result.enqueued_count,
            skipped_count=result.skipped_count,
        )
