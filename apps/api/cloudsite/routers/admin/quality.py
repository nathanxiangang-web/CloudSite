"""A4 content quality admin routes: todo queue, detection, feedback review.

 Registered under /api/admin/quality/ — automatically protected by
 admin_session_middleware. Domain errors translated to 404/409 envelopes.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ...quality_schemas import (
    BatchDismissInput,
    BatchDismissResultOutput,
    ContentFeedbackListOutput,
    ContentFeedbackSummary,
    DetectInput,
    DetectionResultOutput,
    DetectionRunListOutput,
    DetectionRunSummary,
    DismissTodoInput,
    QualityTodoListOutput,
    QualityTodoSummary,
    ReviewFeedbackInput,
)

router = APIRouter()


def _quality_service():
    from ...services import quality  # noqa: PLC0415

    return quality


def _translate_error(exc: Exception) -> HTTPException:
    service = _quality_service()
    if isinstance(exc, service.QualityTodoNotFound):
        return HTTPException(404, {"code": "QUALITY_TODO_NOT_FOUND", "message": str(exc)})
    if isinstance(exc, service.QualityTodoStateInvalid):
        return HTTPException(409, {"code": "QUALITY_TODO_STATE_INVALID", "message": str(exc)})
    if isinstance(exc, service.ContentFeedbackNotFound):
        return HTTPException(404, {"code": "FEEDBACK_NOT_FOUND", "message": str(exc)})
    return HTTPException(500, {"code": "QUALITY_ERROR", "message": "质量服务错误"})


def _todo_to_response(summary) -> QualityTodoSummary:
    return QualityTodoSummary(
        todo_id=summary.todo_id,
        todo_type=summary.todo_type,
        target_type=summary.target_type,
        target_id=summary.target_id,
        severity=summary.severity,
        title=summary.title,
        detail=summary.detail or None,
        status=summary.status,
        source=summary.source,
        detection_run_id=summary.detection_run_id,
        dismissed_by=summary.dismissed_by,
        dismissed_at=summary.dismissed_at,
        dismiss_reason=summary.dismiss_reason,
        resolved_at=summary.resolved_at,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
    )


def _feedback_to_response(summary) -> ContentFeedbackSummary:
    return ContentFeedbackSummary(
        feedback_id=summary.feedback_id,
        user_id=summary.user_id,
        target_type=summary.target_type,
        target_id=summary.target_id,
        feedback_kind=summary.feedback_kind,
        description=summary.description,
        status=summary.status,
        admin_note=summary.admin_note,
        reviewed_by=summary.reviewed_by,
        reviewed_at=summary.reviewed_at,
        todo_id=summary.todo_id,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
    )


@router.get("/api/admin/quality/todos", response_model=QualityTodoListOutput)
async def list_todos(
    todo_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    target_type: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    from ...main import StateSession

    service = _quality_service()
    async with StateSession() as state:
        items, total = await service.list_quality_todos(
            state,
            todo_type=todo_type,
            status=status,
            target_type=target_type,
            severity=severity,
            page=page,
            page_size=page_size,
        )
        total_pages = max(1, (total + page_size - 1) // page_size)
        return QualityTodoListOutput(
            items=[_todo_to_response(i) for i in items],
            page=page,
            page_size=page_size,
            total=total,
            total_pages=total_pages,
        )


@router.get("/api/admin/quality/todos/{todo_id}", response_model=QualityTodoSummary)
async def get_todo(todo_id: str):
    from ...main import StateSession

    service = _quality_service()
    async with StateSession() as state:
        try:
            summary = await service.get_quality_todo(state, todo_id)
            return _todo_to_response(summary)
        except service.QualityError as exc:
            raise _translate_error(exc) from exc


@router.post("/api/admin/quality/todos/{todo_id}/dismiss", response_model=QualityTodoSummary)
async def dismiss_todo(todo_id: str, body: DismissTodoInput):
    from ...main import StateSession

    service = _quality_service()
    async with StateSession() as state:
        try:
            summary = await service.dismiss_quality_todo(
                state, todo_id, reason=body.reason,
            )
            await state.commit()
            return _todo_to_response(summary)
        except service.QualityError as exc:
            raise _translate_error(exc) from exc


@router.post("/api/admin/quality/todos/{todo_id}/resolve", response_model=QualityTodoSummary)
async def resolve_todo(todo_id: str):
    from ...main import StateSession

    service = _quality_service()
    async with StateSession() as state:
        try:
            summary = await service.resolve_quality_todo(state, todo_id)
            await state.commit()
            return _todo_to_response(summary)
        except service.QualityError as exc:
            raise _translate_error(exc) from exc


@router.post("/api/admin/quality/todos/batch-dismiss", response_model=BatchDismissResultOutput)
async def batch_dismiss_todos(body: BatchDismissInput):
    from ...main import StateSession

    service = _quality_service()
    async with StateSession() as state:
        result = await service.batch_dismiss_quality_todos(
            state, body.todo_ids, reason=body.reason,
        )
        await state.commit()
        return BatchDismissResultOutput(
            results=[
                {"todo_id": tid, "success": ok, "error": err}
                for tid, ok, err in result.results
            ],
            succeeded=result.succeeded,
            failed=result.failed,
        )


@router.post("/api/admin/quality/detect", response_model=DetectionResultOutput)
async def trigger_detection(body: DetectInput):
    from ...main import StateSession, IndexSession

    service = _quality_service()
    async with StateSession() as state, IndexSession() as index:
        result = await service.run_quality_detection(
            state, index, budget_ms=body.budget_ms,
        )
        await state.commit()
        return DetectionResultOutput(
            run_id=result.run_id,
            items_found=result.items_found,
            items_deduplicated=result.items_deduplicated,
            actual_ms=result.actual_ms,
            status=result.status,
            breakdown=result.breakdown or None,
        )


@router.get(
    "/api/admin/quality/detection-runs",
    response_model=DetectionRunListOutput,
)
async def list_detection_runs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    from ...main import StateSession

    service = _quality_service()
    async with StateSession() as state:
        rows, total = await service.list_detection_runs(
            state,
            page=page,
            page_size=page_size,
        )
        return DetectionRunListOutput(
            items=[
                DetectionRunSummary(
                    run_id=row.run_id,
                    started_at=row.started_at,
                    completed_at=row.completed_at,
                    items_found=row.items_found,
                    items_deduplicated=row.items_deduplicated,
                    budget_ms=row.budget_ms,
                    actual_ms=row.actual_ms,
                    status=row.status,
                    breakdown=row.breakdown or None,
                )
                for row in rows
            ],
            total=total,
        )


@router.get("/api/admin/quality/feedback", response_model=ContentFeedbackListOutput)
async def list_feedback(
    status: str | None = Query(default=None),
    target_type: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    from ...main import StateSession

    service = _quality_service()
    async with StateSession() as state:
        items, total = await service.list_content_feedback(
            state,
            status=status,
            target_type=target_type,
            page=page,
            page_size=page_size,
        )
        total_pages = max(1, (total + page_size - 1) // page_size)
        return ContentFeedbackListOutput(
            items=[_feedback_to_response(i) for i in items],
            page=page,
            page_size=page_size,
            total=total,
            total_pages=total_pages,
        )


@router.post(
    "/api/admin/quality/feedback/{feedback_id}/review",
    response_model=ContentFeedbackSummary,
)
async def review_feedback(feedback_id: str, body: ReviewFeedbackInput):
    from ...main import StateSession

    service = _quality_service()
    async with StateSession() as state:
        try:
            summary = await service.review_content_feedback(
                state,
                feedback_id,
                admin_note=body.admin_note,
                new_status=body.status,
            )
            await state.commit()
            return _feedback_to_response(summary)
        except service.QualityError as exc:
            raise _translate_error(exc) from exc