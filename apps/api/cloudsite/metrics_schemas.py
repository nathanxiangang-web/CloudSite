"""G2 metrics collection request/response models.

Strict schema: all request models extra=forbid.
Event ID uses me_ prefix + 32 hex (35 chars).
Baseline ID uses mb_ prefix + 32 hex (35 chars).
Summary ID uses ms_ prefix + 32 hex (35 chars).
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

_EVENT_ID_PATTERN = r"^me_[A-Za-z0-9_-]{32}$"
_BASELINE_ID_PATTERN = r"^mb_[A-Za-z0-9_-]{32}$"
_SUMMARY_ID_PATTERN = r"^ms_[A-Za-z0-9_-]{32}$"


class MetricsConfigResponse(BaseModel):
    enabled: bool
    retention_days: int
    upload_raw_queries: bool


class MetricsConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool | None = None
    retention_days: int | None = None
    upload_raw_queries: bool | None = None


class RecordEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_type: str = Field(min_length=1, max_length=64)
    event_data: dict | None = None
    user_id: str | None = None


class EventResponse(BaseModel):
    id: str
    event_type: str
    event_data: dict | None = None
    user_id: str | None = None
    created_at: datetime


class EventListResponse(BaseModel):
    events: list[EventResponse]
    total: int


class SummaryResponse(BaseModel):
    id: str
    period_start: datetime
    period_end: datetime
    metric_type: str
    value: float
    sample_count: int
    created_at: datetime


class SummaryListResponse(BaseModel):
    summaries: list[SummaryResponse]


class AggregateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period_start: datetime
    period_end: datetime


class AggregateResponse(BaseModel):
    metrics: dict[str, float]


class CaptureBaselineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=128)
    period_start: datetime
    period_end: datetime


class BaselineResponse(BaseModel):
    id: str
    label: str
    period_start: datetime
    period_end: datetime
    summary: dict[str, float]
    created_at: datetime


class BaselineListResponse(BaseModel):
    baselines: list[BaselineResponse]


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    baseline_id: str
    current_start: datetime
    current_end: datetime


class ComparisonMetricEntry(BaseModel):
    baseline: float
    current: float
    delta: float | None = None


class ComparisonResponse(BaseModel):
    baseline_id: str
    baseline_label: str
    metrics: dict[str, ComparisonMetricEntry]


class PurgeResponse(BaseModel):
    purged_count: int