"""A3 AI completion admin routes: config CRUD, draft generation/review, budget.

 Registered under /api/admin/ai/ — automatically protected by
 admin_session_middleware.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ...ai_schemas import (
    BudgetUsageOutput,
    CreateProviderConfigInput,
    DraftListOutput,
    DraftOutput,
    GenerateDraftInput,
    GenerationResultOutput,
    ModifyDraftInput,
    ProviderConfigListOutput,
    ProviderConfigOutput,
    RejectDraftInput,
    UpdateProviderConfigInput,
)

router = APIRouter()


def _service():
    from ...services import ai_completion  # noqa: PLC0415

    return ai_completion


def _translate_error(exc: Exception) -> HTTPException:
    service = _service()
    if isinstance(exc, service.ProviderConfigNotFound):
        return HTTPException(404, {"code": "PROVIDER_CONFIG_NOT_FOUND", "message": str(exc)})
    if isinstance(exc, service.DraftNotFound):
        return HTTPException(404, {"code": "DRAFT_NOT_FOUND", "message": str(exc)})
    if isinstance(exc, service.DraftStateInvalid):
        return HTTPException(409, {"code": "DRAFT_STATE_INVALID", "message": str(exc)})
    if isinstance(exc, service.BudgetExceeded):
        return HTTPException(429, {"code": "BUDGET_EXCEEDED", "message": str(exc)})
    if isinstance(exc, service.NoEnabledProvider):
        return HTTPException(409, {"code": "NO_ENABLED_PROVIDER", "message": str(exc)})
    return HTTPException(500, {"code": "AI_COMPLETION_ERROR", "message": "AI 补全服务错误"})


def _config_to_response(s) -> ProviderConfigOutput:
    return ProviderConfigOutput(
        config_id=s.config_id,
        provider_type=s.provider_type,
        display_name=s.display_name,
        endpoint_url=s.endpoint_url,
        model_name=s.model_name,
        enabled=s.enabled,
        daily_budget_tokens=s.daily_budget_tokens,
        daily_budget_requests=s.daily_budget_requests,
        timeout_seconds=s.timeout_seconds,
        max_retries=s.max_retries,
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


def _draft_to_response(s) -> DraftOutput:
    return DraftOutput(
        draft_id=s.draft_id,
        target_type=s.target_type,
        target_id=s.target_id,
        field_type=s.field_type,
        provider_type=s.provider_type,
        model_name=s.model_name,
        prompt_template_version=s.prompt_template_version,
        source_pointers=s.source_pointers,
        generated_content=s.generated_content,
        candidate_status=s.candidate_status,
        input_material_hash=s.input_material_hash,
        config_id=s.config_id,
        tokens_used=s.tokens_used,
        elapsed_ms=s.elapsed_ms,
        error_message=s.error_message,
        reviewed_by=s.reviewed_by,
        reviewed_at=s.reviewed_at,
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


# ---- config CRUD ----

@router.post("/api/admin/ai/configs", response_model=ProviderConfigOutput, status_code=201)
async def create_config(body: CreateProviderConfigInput):
    from ...main import StateSession

    service = _service()
    async with StateSession() as state:
        summary = await service.create_provider_config(
            state,
            provider_type=body.provider_type,
            display_name=body.display_name,
            endpoint_url=body.endpoint_url,
            api_key_encrypted=body.api_key,
            model_name=body.model_name,
            enabled=body.enabled,
            daily_budget_tokens=body.daily_budget_tokens,
            daily_budget_requests=body.daily_budget_requests,
            timeout_seconds=body.timeout_seconds,
            max_retries=body.max_retries,
        )
        await state.commit()
        return _config_to_response(summary)


@router.get("/api/admin/ai/configs", response_model=ProviderConfigListOutput)
async def list_configs(enabled_only: bool = Query(default=False)):
    from ...main import StateSession

    service = _service()
    async with StateSession() as state:
        items = await service.list_provider_configs(state, enabled_only=enabled_only)
        return ProviderConfigListOutput(items=[_config_to_response(i) for i in items], total=len(items))


@router.get("/api/admin/ai/configs/{config_id}", response_model=ProviderConfigOutput)
async def get_config(config_id: str):
    from ...main import StateSession

    service = _service()
    async with StateSession() as state:
        try:
            summary = await service.get_provider_config(state, config_id)
            return _config_to_response(summary)
        except service.AICompletionError as exc:
            raise _translate_error(exc) from exc


@router.patch("/api/admin/ai/configs/{config_id}", response_model=ProviderConfigOutput)
async def update_config(config_id: str, body: UpdateProviderConfigInput):
    from ...main import StateSession

    service = _service()
    async with StateSession() as state:
        try:
            fields = body.model_dump(exclude_none=True)
            if "api_key" in fields:
                fields["api_key_encrypted"] = fields.pop("api_key")
            summary = await service.update_provider_config(state, config_id, **fields)
            await state.commit()
            return _config_to_response(summary)
        except service.AICompletionError as exc:
            raise _translate_error(exc) from exc


@router.delete("/api/admin/ai/configs/{config_id}", status_code=204)
async def delete_config(config_id: str):
    from ...main import StateSession

    service = _service()
    async with StateSession() as state:
        try:
            await service.delete_provider_config(state, config_id)
            await state.commit()
        except service.AICompletionError as exc:
            raise _translate_error(exc) from exc


@router.get("/api/admin/ai/configs/{config_id}/budget", response_model=BudgetUsageOutput)
async def get_budget(config_id: str):
    from ...main import StateSession

    service = _service()
    async with StateSession() as state:
        try:
            await service.get_provider_config(state, config_id)
        except service.AICompletionError as exc:
            raise _translate_error(exc) from exc
        usage = await service.get_budget_usage(state, config_id)
        return BudgetUsageOutput(**usage)


# ---- draft generation and review ----

@router.post("/api/admin/ai/drafts/generate", response_model=GenerationResultOutput)
async def generate_draft(body: GenerateDraftInput):
    from ...main import StateSession

    service = _service()
    async with StateSession() as state:
        try:
            result = await service.generate_draft(
                state,
                target_entry_id=body.target_entry_id,
                field_type=body.field_type,
                config_id=body.config_id,
                generated_content=body.generated_content,
                tokens_used=body.tokens_used,
                elapsed_ms=body.elapsed_ms,
            )
            await state.commit()
            return GenerationResultOutput(
                draft_id=result.draft_id,
                field_type=result.field_type,
                generated_content=result.generated_content,
                tokens_used=result.tokens_used,
                elapsed_ms=result.elapsed_ms,
                status=result.status,
            )
        except service.AICompletionError as exc:
            raise _translate_error(exc) from exc


@router.get("/api/admin/ai/drafts", response_model=DraftListOutput)
async def list_drafts(
    target_id: str | None = Query(default=None),
    field_type: str | None = Query(default=None),
    candidate_status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    from ...main import StateSession

    service = _service()
    async with StateSession() as state:
        items, total = await service.list_drafts(
            state,
            target_id=target_id,
            field_type=field_type,
            candidate_status=candidate_status,
            page=page,
            page_size=page_size,
        )
        total_pages = max(1, (total + page_size - 1) // page_size)
        return DraftListOutput(
            items=[_draft_to_response(i) for i in items],
            page=page,
            page_size=page_size,
            total=total,
            total_pages=total_pages,
        )


@router.get("/api/admin/ai/drafts/{draft_id}", response_model=DraftOutput)
async def get_draft(draft_id: str):
    from ...main import StateSession

    service = _service()
    async with StateSession() as state:
        try:
            summary = await service.get_draft(state, draft_id)
            return _draft_to_response(summary)
        except service.AICompletionError as exc:
            raise _translate_error(exc) from exc


@router.post("/api/admin/ai/drafts/{draft_id}/accept", response_model=DraftOutput)
async def accept_draft(draft_id: str):
    from ...main import StateSession

    service = _service()
    async with StateSession() as state:
        try:
            summary = await service.accept_draft(state, draft_id)
            await state.commit()
            return _draft_to_response(summary)
        except service.AICompletionError as exc:
            raise _translate_error(exc) from exc


@router.post("/api/admin/ai/drafts/{draft_id}/reject", response_model=DraftOutput)
async def reject_draft(draft_id: str, body: RejectDraftInput):
    from ...main import StateSession

    service = _service()
    async with StateSession() as state:
        try:
            summary = await service.reject_draft(state, draft_id, reason=body.reason)
            await state.commit()
            return _draft_to_response(summary)
        except service.AICompletionError as exc:
            raise _translate_error(exc) from exc


@router.post("/api/admin/ai/drafts/{draft_id}/modify", response_model=DraftOutput)
async def modify_draft(draft_id: str, body: ModifyDraftInput):
    from ...main import StateSession

    service = _service()
    async with StateSession() as state:
        try:
            summary = await service.modify_draft(state, draft_id, modified_content=body.modified_content)
            await state.commit()
            return _draft_to_response(summary)
        except service.AICompletionError as exc:
            raise _translate_error(exc) from exc