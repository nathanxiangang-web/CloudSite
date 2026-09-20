"""A3 optional AI content completion service.

 Manages AI provider configs, generates content drafts (summary/tags/
 aliases/usage_note), and supports admin review (accept/reject/modify).
 Budget-controlled: daily token and request limits per provider config.
 AI is optional — disabled configs never participate, and core functions
 work without any AI integration.

 Transaction ownership stays with the caller.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cloudsite.models import (
    AIBudgetUsage,
    AIGenerationDraft,
    AIProviderConfig,
    CatalogEntry,
    utcnow,
)

CONFIG_ID_PREFIX = "ac_"
DRAFT_ID_PREFIX = "ad_"
_ID_HEX_LEN = 32
PROMPT_TEMPLATE_VERSION = "1.0.0"

_FIELD_SUMMARY = "summary"
_FIELD_TAGS = "tags"
_FIELD_ALIASES = "aliases"
_FIELD_USAGE_NOTE = "usage_note"


class AICompletionError(Exception):
    """AI completion service error base class."""


class ProviderConfigNotFound(AICompletionError):
    def __init__(self, config_id: str):
        super().__init__(f"provider config not found: {config_id}")
        self.config_id = config_id


class DraftNotFound(AICompletionError):
    def __init__(self, draft_id: str):
        super().__init__(f"draft not found: {draft_id}")
        self.draft_id = draft_id


class DraftStateInvalid(AICompletionError):
    def __init__(self, draft_id: str, reason: str):
        super().__init__(f"draft {draft_id} state invalid: {reason}")
        self.draft_id = draft_id
        self.reason = reason


class BudgetExceeded(AICompletionError):
    def __init__(self, config_id: str, reason: str):
        super().__init__(f"budget exceeded for config {config_id}: {reason}")
        self.config_id = config_id


class NoEnabledProvider(AICompletionError):
    def __init__(self):
        super().__init__("no enabled AI provider config found")


def _new_id(prefix: str) -> str:
    return prefix + secrets.token_hex(_ID_HEX_LEN // 2)


def _today() -> str:
    return utcnow().strftime("%Y-%m-%d")


def _hash_material(material: dict[str, Any]) -> str:
    raw = json.dumps(material, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:64]


def _build_input_material(entry: CatalogEntry, field_type: str) -> dict[str, Any]:
    return {
        "entry_id": entry.entry_id,
        "title": entry.title,
        "content_type": entry.content_type,
        "existing_summary": entry.summary,
        "field_type": field_type,
    }


# ---- config management ----

@dataclass
class ProviderConfigSummary:
    config_id: str
    provider_type: str
    display_name: str
    endpoint_url: str
    model_name: str
    enabled: bool
    daily_budget_tokens: int
    daily_budget_requests: int
    timeout_seconds: int
    max_retries: int
    created_at: datetime
    updated_at: datetime


async def create_provider_config(
    state: AsyncSession,
    *,
    provider_type: str,
    display_name: str,
    endpoint_url: str = "",
    api_key_encrypted: str = "",
    model_name: str = "",
    enabled: bool = False,
    daily_budget_tokens: int = 100000,
    daily_budget_requests: int = 100,
    timeout_seconds: int = 30,
    max_retries: int = 2,
) -> ProviderConfigSummary:
    config = AIProviderConfig(
        config_id=_new_id(CONFIG_ID_PREFIX),
        provider_type=provider_type,
        display_name=display_name,
        endpoint_url=endpoint_url,
        api_key_encrypted=api_key_encrypted,
        model_name=model_name,
        enabled=enabled,
        daily_budget_tokens=daily_budget_tokens,
        daily_budget_requests=daily_budget_requests,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    )
    state.add(config)
    await state.flush()
    return _config_to_summary(config)


async def get_provider_config(state: AsyncSession, config_id: str) -> ProviderConfigSummary:
    row = await state.scalar(select(AIProviderConfig).where(AIProviderConfig.config_id == config_id))
    if row is None:
        raise ProviderConfigNotFound(config_id)
    return _config_to_summary(row)


async def list_provider_configs(
    state: AsyncSession,
    *,
    enabled_only: bool = False,
) -> list[ProviderConfigSummary]:
    q = select(AIProviderConfig)
    if enabled_only:
        q = q.where(AIProviderConfig.enabled == True)  # noqa: E712
    rows = (await state.scalars(q.order_by(AIProviderConfig.created_at.desc()))).all()
    return [_config_to_summary(r) for r in rows]


_UPDATABLE_FIELDS = frozenset({
    "display_name", "endpoint_url", "api_key", "model_name",
    "enabled", "system_prompt", "max_tokens", "temperature",
})


async def update_provider_config(
    state: AsyncSession,
    config_id: str,
    **fields: Any,
) -> ProviderConfigSummary:
    row = await state.scalar(select(AIProviderConfig).where(AIProviderConfig.config_id == config_id))
    if row is None:
        raise ProviderConfigNotFound(config_id)
    for key, val in fields.items():
        if key not in _UPDATABLE_FIELDS:
            raise AICompletionError(f"field \{key}\ is not updatable")
        if hasattr(row, key) and val is not None:
            setattr(row, key, val)
    row.updated_at = utcnow()
    await state.flush()
    return _config_to_summary(row)


async def delete_provider_config(state: AsyncSession, config_id: str) -> None:
    row = await state.scalar(select(AIProviderConfig).where(AIProviderConfig.config_id == config_id))
    if row is None:
        raise ProviderConfigNotFound(config_id)
    await state.delete(row)
    await state.flush()


# ---- budget control ----

async def _check_budget(state: AsyncSession, config: AIProviderConfig) -> None:
    today = _today()
    usage = await state.scalar(
        select(AIBudgetUsage).where(
            AIBudgetUsage.config_id == config.config_id,
            AIBudgetUsage.date == today,
        )
    )
    if usage is None:
        return
    if usage.requests_used >= config.daily_budget_requests:
        raise BudgetExceeded(config.config_id, f"daily request limit reached ({usage.requests_used}/{config.daily_budget_requests})")
    if usage.tokens_used >= config.daily_budget_tokens:
        raise BudgetExceeded(config.config_id, f"daily token limit reached ({usage.tokens_used}/{config.daily_budget_tokens})")


async def _record_usage(state: AsyncSession, config_id: str, tokens: int) -> None:
    today = _today()
    usage = await state.scalar(
        select(AIBudgetUsage).where(
            AIBudgetUsage.config_id == config_id,
            AIBudgetUsage.date == today,
        )
    )
    if usage is None:
        usage = AIBudgetUsage(config_id=config_id, date=today, tokens_used=0, requests_used=0)
        state.add(usage)
    usage.tokens_used += tokens
    usage.requests_used += 1
    usage.updated_at = utcnow()
    await state.flush()


async def get_budget_usage(state: AsyncSession, config_id: str) -> dict[str, Any]:
    today = _today()
    usage = await state.scalar(
        select(AIBudgetUsage).where(
            AIBudgetUsage.config_id == config_id,
            AIBudgetUsage.date == today,
        )
    )
    if usage is None:
        return {"date": today, "tokens_used": 0, "requests_used": 0}
    return {"date": usage.date, "tokens_used": usage.tokens_used, "requests_used": usage.requests_used}


# ---- generation ----

@dataclass
class GenerationResult:
    draft_id: str
    field_type: str
    generated_content: str
    tokens_used: int
    elapsed_ms: int
    status: str


async def generate_draft(
    state: AsyncSession,
    *,
    target_entry_id: str,
    field_type: str,
    config_id: str | None = None,
    generated_content: str = "",
    tokens_used: int = 0,
    elapsed_ms: int = 0,
) -> GenerationResult:
    """Generate an AI draft for a catalog entry field.

    In production, the caller (or a background worker) would invoke the AI
    provider's API and pass the generated_content/tokens_used/elapsed_ms.
    This service function handles deduplication, budget tracking, and draft
    persistence. It does NOT call any external AI API directly.
    """
    entry = await state.scalar(select(CatalogEntry).where(CatalogEntry.entry_id == target_entry_id))
    if entry is None:
        raise DraftNotFound(target_entry_id)

    if config_id is None:
        config = await state.scalar(
            select(AIProviderConfig).where(AIProviderConfig.enabled == True).order_by(AIProviderConfig.created_at.asc())  # noqa: E712
        )
        if config is None:
            raise NoEnabledProvider()
        config_id = config.config_id
        provider_type = config.provider_type
        model_name = config.model_name
    else:
        config = await state.scalar(select(AIProviderConfig).where(AIProviderConfig.config_id == config_id))
        if config is None:
            raise ProviderConfigNotFound(config_id)
        if not config.enabled:
            raise DraftStateInvalid(config_id, "provider config is not enabled")
        provider_type = config.provider_type
        model_name = config.model_name

    await _check_budget(state, config)

    material = _build_input_material(entry, field_type)
    material_hash = _hash_material(material)

    existing = await state.scalar(
        select(AIGenerationDraft).where(
            AIGenerationDraft.target_type == "entry",
            AIGenerationDraft.target_id == target_entry_id,
            AIGenerationDraft.field_type == field_type,
            AIGenerationDraft.input_material_hash == material_hash,
            AIGenerationDraft.candidate_status == "pending",
        )
    )
    if existing is not None:
        return GenerationResult(
            draft_id=existing.draft_id,
            field_type=existing.field_type,
            generated_content=existing.generated_content,
            tokens_used=existing.tokens_used,
            elapsed_ms=existing.elapsed_ms,
            status="pending",
        )

    source_pointers = json.dumps([
        {"type": "entry", "id": entry.entry_id, "field": "title"},
        {"type": "entry", "id": entry.entry_id, "field": "content_type"},
    ], ensure_ascii=False)

    draft = AIGenerationDraft(
        draft_id=_new_id(DRAFT_ID_PREFIX),
        target_type="entry",
        target_id=target_entry_id,
        field_type=field_type,
        provider_type=provider_type,
        model_name=model_name,
        prompt_template_version=PROMPT_TEMPLATE_VERSION,
        source_pointers_json=source_pointers,
        generated_content=generated_content,
        candidate_status="pending",
        input_material_hash=material_hash,
        config_id=config_id,
        tokens_used=tokens_used,
        elapsed_ms=elapsed_ms,
    )
    state.add(draft)
    await state.flush()

    await _record_usage(state, config_id, tokens_used)

    return GenerationResult(
        draft_id=draft.draft_id,
        field_type=field_type,
        generated_content=generated_content,
        tokens_used=tokens_used,
        elapsed_ms=elapsed_ms,
        status="pending",
    )


# ---- draft review ----

@dataclass
class DraftSummary:
    draft_id: str
    target_type: str
    target_id: str
    field_type: str
    provider_type: str
    model_name: str
    prompt_template_version: str
    source_pointers: list[dict] | None
    generated_content: str
    candidate_status: str
    input_material_hash: str
    config_id: str | None
    tokens_used: int
    elapsed_ms: int
    error_message: str
    reviewed_by: str
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime


async def list_drafts(
    state: AsyncSession,
    *,
    target_id: str | None = None,
    field_type: str | None = None,
    candidate_status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[DraftSummary], int]:
    conditions = []
    if target_id:
        conditions.append(AIGenerationDraft.target_id == target_id)
    if field_type:
        conditions.append(AIGenerationDraft.field_type == field_type)
    if candidate_status:
        conditions.append(AIGenerationDraft.candidate_status == candidate_status)

    base = select(AIGenerationDraft)
    count_q = select(func.count()).select_from(AIGenerationDraft)
    if conditions:
        base = base.where(and_(*conditions))
        count_q = count_q.where(and_(*conditions))

    total = int(await state.scalar(count_q) or 0)
    offset = (page - 1) * page_size
    rows = (await state.scalars(
        base.order_by(AIGenerationDraft.created_at.desc()).offset(offset).limit(page_size)
    )).all()
    return [_draft_to_summary(r) for r in rows], total


async def get_draft(state: AsyncSession, draft_id: str) -> DraftSummary:
    row = await state.scalar(select(AIGenerationDraft).where(AIGenerationDraft.draft_id == draft_id))
    if row is None:
        raise DraftNotFound(draft_id)
    return _draft_to_summary(row)


async def accept_draft(
    state: AsyncSession,
    draft_id: str,
    *,
    reviewed_by: str = "admin",
) -> DraftSummary:
    row = await state.scalar(select(AIGenerationDraft).where(AIGenerationDraft.draft_id == draft_id))
    if row is None:
        raise DraftNotFound(draft_id)
    if row.candidate_status != "pending":
        raise DraftStateInvalid(draft_id, f"cannot accept draft with status '{row.candidate_status}'")
    row.candidate_status = "accepted"
    row.reviewed_by = reviewed_by
    row.reviewed_at = utcnow()
    row.updated_at = utcnow()

    if row.field_type == "summary":
        entry = await state.scalar(select(CatalogEntry).where(CatalogEntry.entry_id == row.target_id))
        if entry is not None:
            entry.summary = row.generated_content[:1000]
            entry.updated_at = utcnow()

    await state.flush()
    return _draft_to_summary(row)


async def reject_draft(
    state: AsyncSession,
    draft_id: str,
    *,
    reviewed_by: str = "admin",
    reason: str = "",
) -> DraftSummary:
    row = await state.scalar(select(AIGenerationDraft).where(AIGenerationDraft.draft_id == draft_id))
    if row is None:
        raise DraftNotFound(draft_id)
    if row.candidate_status != "pending":
        raise DraftStateInvalid(draft_id, f"cannot reject draft with status '{row.candidate_status}'")
    row.candidate_status = "rejected"
    row.reviewed_by = reviewed_by
    row.reviewed_at = utcnow()
    row.error_message = reason
    row.updated_at = utcnow()
    await state.flush()
    return _draft_to_summary(row)


async def modify_draft(
    state: AsyncSession,
    draft_id: str,
    *,
    reviewed_by: str = "admin",
    modified_content: str = "",
) -> DraftSummary:
    row = await state.scalar(select(AIGenerationDraft).where(AIGenerationDraft.draft_id == draft_id))
    if row is None:
        raise DraftNotFound(draft_id)
    if row.candidate_status != "pending":
        raise DraftStateInvalid(draft_id, f"cannot modify draft with status '{row.candidate_status}'")
    row.candidate_status = "modified"
    row.generated_content = modified_content
    row.reviewed_by = reviewed_by
    row.reviewed_at = utcnow()
    row.updated_at = utcnow()

    if row.field_type == "summary":
        entry = await state.scalar(select(CatalogEntry).where(CatalogEntry.entry_id == row.target_id))
        if entry is not None:
            entry.summary = modified_content[:1000]
            entry.updated_at = utcnow()

    await state.flush()
    return _draft_to_summary(row)


# ---- helpers ----

def _config_to_summary(row: AIProviderConfig) -> ProviderConfigSummary:
    return ProviderConfigSummary(
        config_id=row.config_id,
        provider_type=row.provider_type,
        display_name=row.display_name,
        endpoint_url=row.endpoint_url,
        model_name=row.model_name,
        enabled=row.enabled,
        daily_budget_tokens=row.daily_budget_tokens,
        daily_budget_requests=row.daily_budget_requests,
        timeout_seconds=row.timeout_seconds,
        max_retries=row.max_retries,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _draft_to_summary(row: AIGenerationDraft) -> DraftSummary:
    pointers = None
    if row.source_pointers_json and row.source_pointers_json != "[]":
        try:
            pointers = json.loads(row.source_pointers_json)
        except (json.JSONDecodeError, TypeError):
            pointers = None
    return DraftSummary(
        draft_id=row.draft_id,
        target_type=row.target_type,
        target_id=row.target_id,
        field_type=row.field_type,
        provider_type=row.provider_type,
        model_name=row.model_name,
        prompt_template_version=row.prompt_template_version,
        source_pointers=pointers,
        generated_content=row.generated_content,
        candidate_status=row.candidate_status,
        input_material_hash=row.input_material_hash,
        config_id=row.config_id,
        tokens_used=row.tokens_used,
        elapsed_ms=row.elapsed_ms,
        error_message=row.error_message,
        reviewed_by=row.reviewed_by,
        reviewed_at=row.reviewed_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )