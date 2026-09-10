"""A2 整理工作台请求与响应模型。

严格 schema：所有请求模型 extra=forbid，仅接受稳定字符串 ID 与受控字段。
建议 ID 使用 cs_ 前缀 + 32 hex（35 字符），匹配 CatalogSuggestion.suggestion_id。
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .catalog_metadata_schemas import CatalogRevisionSummary

_SUGGESTION_ID_PATTERN = r"^cs_[A-Za-z0-9_-]{32}$"
_SUGGESTION_KIND = Literal[
    "new_entry", "new_release", "asset", "candidate_duplicate", "conflict"
]
_SUGGESTION_STATUS = Literal["pending", "reviewed", "applied", "rejected"]


# ---- 响应 schema ----

class SuggestionSummary(BaseModel):
    suggestion_id: str
    source_file_id: str
    file_fingerprint: str
    parser_version: str
    suggestion_kind: str
    target_entry_id: str | None = None
    target_release_id: str | None = None
    target_asset_id: str | None = None
    suggested_fields: dict | None = None
    evidence: dict | None = None
    confidence: float = 0.0
    status: str = "pending"
    reviewed_by: str = ""
    reviewed_at: datetime | None = None
    applied_at: datetime | None = None
    applied_revision_id: str | None = None
    reject_reason: str = ""
    created_at: datetime
    updated_at: datetime


class SuggestionListOutput(BaseModel):
    items: list[SuggestionSummary]
    page: int
    page_size: int
    total: int
    total_pages: int


class ApplyResultSummary(BaseModel):
    suggestion_id: str
    success: bool
    error: str = ""
    entry_id: str | None = None
    release_id: str | None = None
    asset_id: str | None = None


class BatchApplyOutput(BaseModel):
    results: list[ApplyResultSummary]
    succeeded: int
    failed: int


class GenerateOutput(BaseModel):
    created: int
    skipped: int


class RevisionListOutput(BaseModel):
    items: list[CatalogRevisionSummary]
    total: int


# ---- 请求 schema ----

class BatchApplyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    suggestion_ids: list[str] = Field(min_length=1, max_length=500)


class BatchRejectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    suggestion_ids: list[str] = Field(min_length=1, max_length=500)
    reason: str = Field(default="", max_length=2000)


class SuggestionRejectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(default="", max_length=2000)


class GenerateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int = Field(default=200, ge=1, le=2000)
    content_type: str | None = Field(default=None, max_length=40)
