"""G2 metrics collection, aggregation, baseline, and comparison.

Records business events (download_redirect_issued, search_performed,
resource_selected, site_setup_completed, organize_batch_completed),
aggregates them into metric summaries, captures baselines for
before/after comparison, and supports retention-based purging.

Configuration via system_settings:
  metrics_enabled (bool, default true)
  metrics_retention_days (int, default 90)
  metrics_upload_raw_queries (bool, default false)

Transaction ownership stays with the caller.
"""
from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import MetricBaseline, MetricEvent, MetricSummary, SystemSetting, utcnow

EVENT_ID_PREFIX = "me_"
BASELINE_ID_PREFIX = "mb_"
SUMMARY_ID_PREFIX = "ms_"
_ID_HEX_LEN = 32

SETTING_METRICS_ENABLED = "metrics_enabled"
SETTING_METRICS_RETENTION_DAYS = "metrics_retention_days"
SETTING_METRICS_UPLOAD_RAW_QUERIES = "metrics_upload_raw_queries"

DEFAULT_RETENTION_DAYS = 90

EVENT_DOWNLOAD_REDIRECT = "download_redirect_issued"
EVENT_SEARCH_PERFORMED = "search_performed"
EVENT_RESOURCE_SELECTED = "resource_selected"
EVENT_SITE_SETUP_COMPLETED = "site_setup_completed"
EVENT_ORGANIZE_BATCH_COMPLETED = "organize_batch_completed"
EVENT_UPDATE_REVISIT = "update_revisit"

METRIC_RESOURCE_SELECTION_SUCCESS_RATE = "resource_selection_success_rate"
METRIC_ORGANIZE_TIME_PER_100 = "organize_time_per_100"
METRIC_SEARCH_HIT_RATE = "search_hit_rate"
METRIC_NO_RESULT_RATE = "no_result_rate"
METRIC_FIRST_SITE_SETUP_TIME = "first_site_setup_time"
METRIC_UPDATE_REVISIT_RATE = "update_revisit_rate"
METRIC_DOWNLOAD_REDIRECT_COUNT = "download_redirect_count"


class MetricsError(Exception):
    """Metrics service error base class."""


class BaselineNotFound(MetricsError):
    def __init__(self, baseline_id: str):
        super().__init__(f"Baseline {baseline_id} not found")


@dataclass(frozen=True, slots=True)
class MetricsConfig:
    enabled: bool
    retention_days: int
    upload_raw_queries: bool


@dataclass(frozen=True, slots=True)
class EventRecord:
    id: str
    event_type: str
    event_data: dict | None
    user_id: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SummaryRecord:
    id: str
    period_start: datetime
    period_end: datetime
    metric_type: str
    value: float
    sample_count: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class BaselineRecord:
    id: str
    label: str
    period_start: datetime
    period_end: datetime
    summary: dict[str, float]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    baseline_id: str
    baseline_label: str
    metrics: dict[str, dict[str, float | int | None]]


def _new_id(prefix: str) -> str:
    return prefix + secrets.token_hex(_ID_HEX_LEN // 2)


async def get_config(state: AsyncSession) -> MetricsConfig:
    enabled_row = await state.get(SystemSetting, SETTING_METRICS_ENABLED)
    retention_row = await state.get(SystemSetting, SETTING_METRICS_RETENTION_DAYS)
    upload_row = await state.get(SystemSetting, SETTING_METRICS_UPLOAD_RAW_QUERIES)

    enabled = True
    if enabled_row and enabled_row.value:
        enabled = enabled_row.value.lower() in ("true", "1", "yes")

    retention = DEFAULT_RETENTION_DAYS
    if retention_row and retention_row.value:
        try:
            retention = int(retention_row.value)
        except ValueError:
            pass

    upload_raw = False
    if upload_row and upload_row.value:
        upload_raw = upload_row.value.lower() in ("true", "1", "yes")

    return MetricsConfig(enabled=enabled, retention_days=retention, upload_raw_queries=upload_raw)


async def try_record(state: AsyncSession, event_type: str,
                     event_data: dict | None = None,
                     user_id: str | None = None) -> None:
    """Best-effort event recording. Never raises."""
    try:
        await record_event(state, event_type, event_data, user_id)
    except Exception:
        pass


async def try_record_committed(state: AsyncSession, event_type: str,
                               event_data: dict | None = None,
                               user_id: str | None = None) -> None:
    """Best-effort event recording with commit. Never raises.

    Records the event and commits the session so the metric row persists
    even when the caller closes the session without committing. Used by
    public routes that own a short-lived state session and must not let
    metrics storage failure change the user response.
    """
    try:
        await record_event(state, event_type, event_data, user_id)
        await state.commit()
    except Exception:
        pass


async def set_config(state: AsyncSession, enabled: bool | None = None,
                     retention_days: int | None = None,
                     upload_raw_queries: bool | None = None) -> MetricsConfig:
    if enabled is not None:
        row = await state.get(SystemSetting, SETTING_METRICS_ENABLED) or SystemSetting(key=SETTING_METRICS_ENABLED)
        row.value = "true" if enabled else "false"
        row.value_type = "boolean"
        state.add(row)

    if retention_days is not None:
        if retention_days < 1:
            raise MetricsError("retention_days must be >= 1")
        row = await state.get(SystemSetting, SETTING_METRICS_RETENTION_DAYS) or SystemSetting(key=SETTING_METRICS_RETENTION_DAYS)
        row.value = str(retention_days)
        row.value_type = "integer"
        state.add(row)

    if upload_raw_queries is not None:
        row = await state.get(SystemSetting, SETTING_METRICS_UPLOAD_RAW_QUERIES) or SystemSetting(key=SETTING_METRICS_UPLOAD_RAW_QUERIES)
        row.value = "true" if upload_raw_queries else "false"
        row.value_type = "boolean"
        state.add(row)

    await state.flush()
    return await get_config(state)


async def record_event(state: AsyncSession, event_type: str,
                       event_data: dict | None = None,
                       user_id: str | None = None) -> MetricEvent:
    config = await get_config(state)
    if not config.enabled:
        raise MetricsError("Metrics collection is disabled")

    if event_data and not config.upload_raw_queries:
        event_data = {k: v for k, v in event_data.items() if k != "raw_query"}

    event = MetricEvent(
        id=_new_id(EVENT_ID_PREFIX),
        event_type=event_type,
        event_data=json.dumps(event_data) if event_data else None,
        user_id=user_id,
    )
    state.add(event)
    await state.flush()
    return event


async def list_events(state: AsyncSession, event_type: str | None = None,
                      user_id: str | None = None,
                      limit: int = 100, offset: int = 0) -> list[EventRecord]:
    stmt = select(MetricEvent).order_by(MetricEvent.created_at.desc())
    if event_type:
        stmt = stmt.where(MetricEvent.event_type == event_type)
    if user_id:
        stmt = stmt.where(MetricEvent.user_id == user_id)
    stmt = stmt.limit(limit).offset(offset)
    result = await state.execute(stmt)
    rows = result.scalars().all()
    return [
        EventRecord(
            id=r.id,
            event_type=r.event_type,
            event_data=json.loads(r.event_data) if r.event_data else None,
            user_id=r.user_id,
            created_at=r.created_at,
        )
        for r in rows
    ]


async def aggregate_metrics(state: AsyncSession,
                            period_start: datetime,
                            period_end: datetime) -> dict[str, float]:
    stmt = select(MetricEvent).where(
        MetricEvent.created_at >= period_start,
        MetricEvent.created_at < period_end,
    )
    result = await state.execute(stmt)
    events = result.scalars().all()

    metrics: dict[str, float] = {}

    download_count = sum(1 for e in events if e.event_type == EVENT_DOWNLOAD_REDIRECT)
    metrics[METRIC_DOWNLOAD_REDIRECT_COUNT] = float(download_count)

    search_events = [e for e in events if e.event_type == EVENT_SEARCH_PERFORMED]
    if search_events:
        hits = 0
        no_result = 0
        for e in search_events:
            data = json.loads(e.event_data) if e.event_data else {}
            result_count = data.get("result_count", 0)
            if result_count > 0:
                hits += 1
            else:
                no_result += 1
        metrics[METRIC_SEARCH_HIT_RATE] = hits / len(search_events)
        metrics[METRIC_NO_RESULT_RATE] = no_result / len(search_events)
    else:
        metrics[METRIC_SEARCH_HIT_RATE] = 0.0
        metrics[METRIC_NO_RESULT_RATE] = 0.0

    selection_events = [e for e in events if e.event_type == EVENT_RESOURCE_SELECTED]
    if selection_events:
        successes = 0
        for e in selection_events:
            data = json.loads(e.event_data) if e.event_data else {}
            if data.get("success", False):
                successes += 1
        metrics[METRIC_RESOURCE_SELECTION_SUCCESS_RATE] = successes / len(selection_events)
    else:
        metrics[METRIC_RESOURCE_SELECTION_SUCCESS_RATE] = 0.0

    setup_events = [e for e in events if e.event_type == EVENT_SITE_SETUP_COMPLETED]
    if setup_events:
        total_ms = 0.0
        for e in setup_events:
            data = json.loads(e.event_data) if e.event_data else {}
            total_ms += data.get("elapsed_ms", 0)
        metrics[METRIC_FIRST_SITE_SETUP_TIME] = total_ms / len(setup_events)
    else:
        metrics[METRIC_FIRST_SITE_SETUP_TIME] = 0.0

    organize_events = [e for e in events if e.event_type == EVENT_ORGANIZE_BATCH_COMPLETED]
    if organize_events:
        total_ms = 0.0
        total_items = 0
        for e in organize_events:
            data = json.loads(e.event_data) if e.event_data else {}
            total_ms += data.get("elapsed_ms", 0)
            total_items += data.get("item_count", 0)
        if total_items > 0:
            metrics[METRIC_ORGANIZE_TIME_PER_100] = total_ms / total_items * 100
        else:
            metrics[METRIC_ORGANIZE_TIME_PER_100] = 0.0
    else:
        metrics[METRIC_ORGANIZE_TIME_PER_100] = 0.0

    revisit_events = [e for e in events if e.event_type == EVENT_UPDATE_REVISIT]
    metrics[METRIC_UPDATE_REVISIT_RATE] = float(len(revisit_events))

    return metrics


async def save_summaries(state: AsyncSession,
                         period_start: datetime,
                         period_end: datetime) -> list[MetricSummary]:
    metrics = await aggregate_metrics(state, period_start, period_end)
    summaries: list[MetricSummary] = []
    for metric_type, value in metrics.items():
        s = MetricSummary(
            id=_new_id(SUMMARY_ID_PREFIX),
            period_start=period_start,
            period_end=period_end,
            metric_type=metric_type,
            value=value,
            sample_count=1,
        )
        state.add(s)
        summaries.append(s)
    await state.flush()
    return summaries


async def get_summaries(state: AsyncSession,
                        period_start: datetime | None = None,
                        period_end: datetime | None = None) -> list[SummaryRecord]:
    stmt = select(MetricSummary).order_by(MetricSummary.created_at.desc())
    if period_start:
        stmt = stmt.where(MetricSummary.period_start >= period_start)
    if period_end:
        stmt = stmt.where(MetricSummary.period_end <= period_end)
    result = await state.execute(stmt)
    rows = result.scalars().all()
    return [
        SummaryRecord(
            id=r.id,
            period_start=r.period_start,
            period_end=r.period_end,
            metric_type=r.metric_type,
            value=r.value,
            sample_count=r.sample_count,
            created_at=r.created_at,
        )
        for r in rows
    ]


async def capture_baseline(state: AsyncSession, label: str,
                           period_start: datetime,
                           period_end: datetime) -> MetricBaseline:
    metrics = await aggregate_metrics(state, period_start, period_end)
    baseline = MetricBaseline(
        id=_new_id(BASELINE_ID_PREFIX),
        label=label,
        period_start=period_start,
        period_end=period_end,
        summary_json=json.dumps(metrics),
    )
    state.add(baseline)
    await state.flush()
    return baseline


async def list_baselines(state: AsyncSession) -> list[BaselineRecord]:
    result = await state.execute(select(MetricBaseline).order_by(MetricBaseline.created_at.desc()))
    rows = result.scalars().all()
    return [
        BaselineRecord(
            id=r.id,
            label=r.label,
            period_start=r.period_start,
            period_end=r.period_end,
            summary=json.loads(r.summary_json),
            created_at=r.created_at,
        )
        for r in rows
    ]


async def compare_with_baseline(state: AsyncSession, baseline_id: str,
                                current_start: datetime,
                                current_end: datetime) -> ComparisonResult:
    baseline = await state.get(MetricBaseline, baseline_id)
    if not baseline:
        raise BaselineNotFound(baseline_id)

    baseline_metrics = json.loads(baseline.summary_json)
    current_metrics = await aggregate_metrics(state, current_start, current_end)

    all_keys = set(baseline_metrics) | set(current_metrics)
    comparison: dict[str, dict[str, float | int | None]] = {}
    for key in sorted(all_keys):
        b_val = baseline_metrics.get(key)
        c_val = current_metrics.get(key)
        delta = None
        if b_val is not None and c_val is not None:
            delta = c_val - b_val
        comparison[key] = {
            "baseline": b_val if b_val is not None else 0.0,
            "current": c_val if c_val is not None else 0.0,
            "delta": delta,
        }

    return ComparisonResult(
        baseline_id=baseline.id,
        baseline_label=baseline.label,
        metrics=comparison,
    )


async def purge_old_events(state: AsyncSession, retention_days: int | None = None) -> int:
    if retention_days is None:
        config = await get_config(state)
        retention_days = config.retention_days

    cutoff = utcnow() - timedelta(days=retention_days)
    stmt = delete(MetricEvent).where(MetricEvent.created_at < cutoff)
    result = await state.execute(stmt)
    await state.flush()
    return result.rowcount or 0


async def get_event_count(state: AsyncSession, event_type: str | None = None) -> int:
    stmt = select(func.count(MetricEvent.id))
    if event_type:
        stmt = stmt.where(MetricEvent.event_type == event_type)
    result = await state.execute(stmt)
    return result.scalar() or 0