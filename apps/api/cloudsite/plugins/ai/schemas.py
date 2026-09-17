"""A3 AI content completion request/response models."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

_PROVIDER_TYPE = Literal["local_ollama", "openai_compatible", "custom"]
_FIELD_TYPE = Literal["summary", "tags", "aliases", "usage_note"]
_DRAFT_STATUS = Literal["pending", "accepted", "rejected", "modified"]


# ---- response schema ----

class ProviderConfigOutput(BaseModel):
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


class ProviderConfigListOutput(BaseModel):
    items: list[ProviderConfigOutput]
    total: int


class DraftOutput(BaseModel):
    draft_id: str
    target_type: str
    target_id: str
    field_type: str
    provider_type: str
    model_name: str
    prompt_template_version: str
    source_pointers: list[dict] | None = None
    generated_content: str
    candidate_status: str
    input_material_hash: str
    config_id: str | None = None
    tokens_used: int = 0
    elapsed_ms: int = 0
    error_message: str = ""
    reviewed_by: str = ""
    reviewed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class DraftListOutput(BaseModel):
    items: list[DraftOutput]
    page: int
    page_size: int
    total: int
    total_pages: int


class GenerationResultOutput(BaseModel):
    draft_id: str
    field_type: str
    generated_content: str
    tokens_used: int
    elapsed_ms: int
    status: str


class BudgetUsageOutput(BaseModel):
    date: str
    tokens_used: int
    requests_used: int


# ---- request schema ----

class CreateProviderConfigInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider_type: _PROVIDER_TYPE
    display_name: str = Field(min_length=1, max_length=100)
    endpoint_url: str = Field(default="", max_length=500)
    api_key: str = Field(default="", max_length=500)
    model_name: str = Field(default="", max_length=100)
    enabled: bool = False
    daily_budget_tokens: int = Field(default=100000, ge=0)
    daily_budget_requests: int = Field(default=100, ge=0)
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    max_retries: int = Field(default=2, ge=0, le=10)


class UpdateProviderConfigInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str | None = Field(default=None, max_length=100)
    endpoint_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=500)
    model_name: str | None = Field(default=None, max_length=100)
    enabled: bool | None = None
    daily_budget_tokens: int | None = Field(default=None, ge=0)
    daily_budget_requests: int | None = Field(default=None, ge=0)
    timeout_seconds: int | None = Field(default=None, ge=1, le=300)
    max_retries: int | None = Field(default=None, ge=0, le=10)


class GenerateDraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_entry_id: str = Field(min_length=1, max_length=64)
    field_type: _FIELD_TYPE
    config_id: str | None = None
    generated_content: str = Field(default="", max_length=10000)
    tokens_used: int = Field(default=0, ge=0)
    elapsed_ms: int = Field(default=0, ge=0)


class RejectDraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(default="", max_length=2000)


class ModifyDraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    modified_content: str = Field(min_length=1, max_length=10000)