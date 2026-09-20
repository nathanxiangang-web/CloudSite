"""A4 content quality and maintenance todo queue request/response models.

 Strict schema: all request models extra=forbid.
 Todo ID uses ct_ prefix + 32 hex (35 chars).
 Feedback ID uses cf_ prefix + 32 hex (35 chars).
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

_TODO_ID_PATTERN = r"^ct_[A-Za-z0-9_-]{32}$"
_FEEDBACK_ID_PATTERN = r"^cf_[A-Za-z0-9_-]{32}$"
_TODO_TYPE = Literal[
    "missing_description", "stale_location", "old_version_review",
    "source_conflict", "suspected_duplicate", "no_result_query",
]
_TODO_STATUS = Literal["open", "dismissed", "resolved", "wontfix"]
_SEVERITY = Literal["low", "medium", "high"]
_TARGET_TYPE = Literal["entry", "release", "asset", "location", "query"]
_FEEDBACK_KIND = Literal["broken_link", "wrong_info", "missing_content", "other"]
_FEEDBACK_STATUS = Literal["pending", "reviewed", "resolved"]


# ---- response schema ----

class QualityTodoSummary(BaseModel):
    todo_id: str
    todo_type: str
    target_type: str
    target_id: str
    severity: str
    title: str
    detail: dict | None = None
    status: str = "open"
    source: str = "auto_detection"
    detection_run_id: str | None = None
    dismissed_by: str = ""
    dismissed_at: datetime | None = None
    dismiss_reason: str = ""
    resolved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class QualityTodoListOutput(BaseModel):
    items: list[QualityTodoSummary]
    page: int
    page_size: int
    total: int
    total_pages: int


class DetectionRunSummary(BaseModel):
    run_id: str
    started_at: datetime
    completed_at: datetime | None = None
    items_found: int = 0
    items_deduplicated: int = 0
    budget_ms: int = 5000
    actual_ms: int | None = None
    status: str = "running"
    breakdown: dict | None = None


class DetectionRunListOutput(BaseModel):
    items: list[DetectionRunSummary]
    total: int


class DetectionResultOutput(BaseModel):
    run_id: str
    items_found: int
    items_deduplicated: int
    actual_ms: int
    status: str
    breakdown: dict | None = None


class BatchDismissResultOutput(BaseModel):
    results: list[dict]
    succeeded: int
    failed: int


class ContentFeedbackSummary(BaseModel):
    feedback_id: str
    user_id: int
    target_type: str
    target_id: str
    feedback_kind: str
    description: str
    status: str = "pending"
    admin_note: str = ""
    reviewed_by: str = ""
    reviewed_at: datetime | None = None
    todo_id: str | None = None
    created_at: datetime
    updated_at: datetime


class ContentFeedbackListOutput(BaseModel):
    items: list[ContentFeedbackSummary]
    page: int
    page_size: int
    total: int
    total_pages: int


# ---- request schema ----

class DismissTodoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(default="", max_length=2000)


class BatchDismissInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    todo_ids: list[str] = Field(min_length=1, max_length=500)
    reason: str = Field(default="", max_length=2000)


class DetectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    budget_ms: int = Field(default=5000, ge=100, le=60000)


class ContentFeedbackInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_type: _TARGET_TYPE
    target_id: str = Field(min_length=1, max_length=64)
    feedback_kind: _FEEDBACK_KIND
    description: str = Field(min_length=1, max_length=1000)


class ReviewFeedbackInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    admin_note: str = Field(default="", max_length=2000)
    status: Literal["reviewed", "resolved"] = "reviewed"