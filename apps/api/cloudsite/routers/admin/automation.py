"""A2 整理工作台管理员路由：建议列表、详情、apply/reject、撤销、生成。

注册在现有 admin 中间件边界下：匿名请求在到达任何 handler 前被中间件拒绝。
服务层域错误翻译为稳定的 404/409/400 信封。
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query

from ...automation_schemas import (
    ApplyResultSummary,
    BatchApplyInput,
    BatchApplyOutput,
    BatchRejectInput,
    GenerateInput,
    GenerateOutput,
    RevisionListOutput,
    SuggestionListOutput,
    SuggestionRejectInput,
    SuggestionSummary,
)
from .catalog_metadata import _revision_to_summary

router = APIRouter()


def _review_service():
    from ...services import suggestion_review  # noqa: PLC0415

    return suggestion_review


def _generator_service():
    from ...services import suggestion_generator  # noqa: PLC0415

    return suggestion_generator


def _translate_error(exc: Exception) -> HTTPException:
    service = _review_service()
    if isinstance(exc, service.SuggestionNotFound):
        return HTTPException(404, {"code": "SUGGESTION_NOT_FOUND", "message": str(exc)})
    if isinstance(exc, service.SuggestionStateInvalid):
        return HTTPException(409, {"code": "SUGGESTION_STATE_INVALID", "message": str(exc)})
    return HTTPException(500, {"code": "SUGGESTION_ERROR", "message": "建议审核服务错误"})


def _decode_json(raw: str) -> dict | None:
    if not raw or raw == "{}":
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _suggestion_to_summary(row) -> SuggestionSummary:
    return SuggestionSummary(
        suggestion_id=row.suggestion_id,
        source_file_id=row.source_file_id,
        file_fingerprint=row.file_fingerprint,
        parser_version=row.parser_version,
        suggestion_kind=row.suggestion_kind,
        target_entry_id=row.target_entry_id,
        target_release_id=row.target_release_id,
        target_asset_id=row.target_asset_id,
        suggested_fields=_decode_json(row.suggested_fields_json),
        evidence=_decode_json(row.evidence_json),
        confidence=row.confidence,
        status=row.status,
        reviewed_by=row.reviewed_by,
        reviewed_at=row.reviewed_at,
        applied_at=row.applied_at,
        applied_revision_id=row.applied_revision_id,
        reject_reason=row.reject_reason,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _total_pages(total: int, page_size: int) -> int:
    return max(1, (total + page_size - 1) // page_size)


@router.get("/api/admin/automation/suggestions", response_model=SuggestionListOutput)
async def admin_suggestions_list(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    suggestion_kind: str | None = Query(default=None),
    status: str | None = Query(default=None),
    target_entry_id: str | None = Query(default=None),
):
    from ...main import StateSession

    service = _review_service()
    offset = (page - 1) * page_size
    async with StateSession() as state:
        rows, total = await service.list_suggestions(
            state,
            suggestion_kind=suggestion_kind,
            status=status,
            target_entry_id=target_entry_id,
            limit=page_size,
            offset=offset,
        )
        return SuggestionListOutput(
            items=[_suggestion_to_summary(row) for row in rows],
            page=page,
            page_size=page_size,
            total=total,
            total_pages=_total_pages(total, page_size),
        )


@router.get(
    "/api/admin/automation/suggestions/{suggestion_id}",
    response_model=SuggestionSummary,
)
async def admin_suggestion_detail(suggestion_id: str):
    from ...main import StateSession

    service = _review_service()
    async with StateSession() as state:
        try:
            row = await service.get_suggestion(state, suggestion_id)
        except service.SuggestionError as exc:
            raise _translate_error(exc) from exc
        return _suggestion_to_summary(row)


@router.post(
    "/api/admin/automation/suggestions/batch-apply",
    response_model=BatchApplyOutput,
)
async def admin_suggestions_batch_apply(payload: BatchApplyInput):
    from ...main import IndexSession, StateSession

    service = _review_service()
    async with StateSession() as state, IndexSession() as index:
        batch = await service.batch_apply_suggestions(
            state, index, payload.suggestion_ids, actor="admin"
        )
        await state.commit()
        return BatchApplyOutput(
            results=[
                ApplyResultSummary(
                    suggestion_id=r.suggestion_id,
                    success=r.success,
                    error=r.error,
                    entry_id=r.entry_id,
                    release_id=r.release_id,
                    asset_id=r.asset_id,
                )
                for r in batch.results
            ],
            succeeded=batch.succeeded,
            failed=batch.failed,
        )


@router.post(
    "/api/admin/automation/suggestions/batch-reject",
    response_model=BatchApplyOutput,
)
async def admin_suggestions_batch_reject(payload: BatchRejectInput):
    from ...main import StateSession

    service = _review_service()
    async with StateSession() as state:
        batch = await service.batch_reject_suggestions(
            state, payload.suggestion_ids, actor="admin", reason=payload.reason
        )
        await state.commit()
        return BatchApplyOutput(
            results=[
                ApplyResultSummary(
                    suggestion_id=r.suggestion_id,
                    success=r.success,
                    error=r.error,
                )
                for r in batch.results
            ],
            succeeded=batch.succeeded,
            failed=batch.failed,
        )


@router.post(
    "/api/admin/automation/suggestions/{suggestion_id}/apply",
    response_model=ApplyResultSummary,
)
async def admin_suggestion_apply(suggestion_id: str):
    from ...main import IndexSession, StateSession

    service = _review_service()
    async with StateSession() as state, IndexSession() as index:
        try:
            result = await service.apply_suggestion(
                state, index, suggestion_id, actor="admin"
            )
        except service.SuggestionError as exc:
            raise _translate_error(exc) from exc
        await state.commit()
        return ApplyResultSummary(
            suggestion_id=result.suggestion_id,
            success=result.success,
            error=result.error,
            entry_id=result.entry_id,
            release_id=result.release_id,
            asset_id=result.asset_id,
        )


@router.post(
    "/api/admin/automation/suggestions/{suggestion_id}/reject",
    response_model=SuggestionSummary,
)
async def admin_suggestion_reject(
    suggestion_id: str, payload: SuggestionRejectInput
):
    from ...main import StateSession

    service = _review_service()
    async with StateSession() as state:
        try:
            row = await service.reject_suggestion(
                state, suggestion_id, actor="admin", reason=payload.reason
            )
        except service.SuggestionError as exc:
            raise _translate_error(exc) from exc
        await state.commit()
        return _suggestion_to_summary(row)


@router.post(
    "/api/admin/automation/suggestions/{suggestion_id}/revert",
    response_model=SuggestionSummary,
)
async def admin_suggestion_revert(suggestion_id: str):
    from ...main import StateSession

    service = _review_service()
    async with StateSession() as state:
        try:
            row = await service.revert_suggestion(
                state, suggestion_id, actor="admin"
            )
        except service.SuggestionError as exc:
            raise _translate_error(exc) from exc
        await state.commit()
        return _suggestion_to_summary(row)


@router.get(
    "/api/admin/automation/suggestions/{suggestion_id}/revisions",
    response_model=RevisionListOutput,
)
async def admin_suggestion_revisions(
    suggestion_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    from ...main import StateSession

    service = _review_service()
    offset = (page - 1) * page_size
    async with StateSession() as state:
        try:
            rows, total = await service.list_suggestion_revisions(
                state, suggestion_id, limit=page_size, offset=offset
            )
        except service.SuggestionError as exc:
            raise _translate_error(exc) from exc
        return RevisionListOutput(
            items=[_revision_to_summary(row) for row in rows], total=total
        )


@router.post("/api/admin/automation/generate", response_model=GenerateOutput)
async def admin_suggestions_generate(payload: GenerateInput):
    from ...main import IndexSession, StateSession

    generator = _generator_service()
    async with StateSession() as state, IndexSession() as index:
        result = await generator.generate_suggestions_batch(
            state, index, limit=payload.limit, content_type=payload.content_type
        )
        await state.commit()
        return GenerateOutput(created=len(result.created), skipped=result.skipped)
