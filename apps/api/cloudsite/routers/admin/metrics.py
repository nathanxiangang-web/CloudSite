"""G2 metrics admin routes: config, events, aggregation, baselines, comparison.

Registered under /api/admin/metrics/ — automatically protected by
admin_session_middleware. Domain errors translated to 404/409 envelopes.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ...metrics_schemas import (
    AggregateRequest,
    AggregateResponse,
    BaselineListResponse,
    BaselineResponse,
    CaptureBaselineRequest,
    CompareRequest,
    ComparisonMetricEntry,
    ComparisonResponse,
    EventListResponse,
    EventResponse,
    MetricsConfigResponse,
    MetricsConfigUpdate,
    PurgeResponse,
    RecordEventRequest,
    SummaryListResponse,
    SummaryResponse,
)

router = APIRouter()


def _metrics_service():
    from ...services import metrics  # noqa: PLC0415

    return metrics


def _translate_error(exc: Exception) -> HTTPException:
    service = _metrics_service()
    if isinstance(exc, service.BaselineNotFound):
        return HTTPException(404, {"code": "BASELINE_NOT_FOUND", "message": str(exc)})
    if isinstance(exc, service.MetricsError):
        return HTTPException(409, {"code": "METRICS_ERROR", "message": str(exc)})
    return HTTPException(500, {"code": "METRICS_ERROR", "message": "指标服务错误"})


@router.get("/api/admin/metrics/config", response_model=MetricsConfigResponse)
async def get_config():
    from ...main import StateSession

    service = _metrics_service()
    async with StateSession() as state:
        cfg = await service.get_config(state)
        return MetricsConfigResponse(
            enabled=cfg.enabled,
            retention_days=cfg.retention_days,
            upload_raw_queries=cfg.upload_raw_queries,
        )


@router.put("/api/admin/metrics/config", response_model=MetricsConfigResponse)
async def update_config(body: MetricsConfigUpdate):
    from ...main import StateSession

    service = _metrics_service()
    async with StateSession() as state:
        try:
            cfg = await service.set_config(
                state,
                enabled=body.enabled,
                retention_days=body.retention_days,
                upload_raw_queries=body.upload_raw_queries,
            )
            await state.commit()
            return MetricsConfigResponse(
                enabled=cfg.enabled,
                retention_days=cfg.retention_days,
                upload_raw_queries=cfg.upload_raw_queries,
            )
        except Exception as exc:
            await state.rollback()
            raise _translate_error(exc)


@router.post("/api/admin/metrics/events", response_model=EventResponse)
async def record_event(body: RecordEventRequest):
    from ...main import StateSession

    service = _metrics_service()
    async with StateSession() as state:
        try:
            event = await service.record_event(
                state,
                event_type=body.event_type,
                event_data=body.event_data,
                user_id=body.user_id,
            )
            await state.commit()
            import json
            return EventResponse(
                id=event.id,
                event_type=event.event_type,
                event_data=json.loads(event.event_data) if event.event_data else None,
                user_id=event.user_id,
                created_at=event.created_at,
            )
        except Exception as exc:
            await state.rollback()
            raise _translate_error(exc)


@router.get("/api/admin/metrics/events", response_model=EventListResponse)
async def list_events(
    event_type: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    from ...main import StateSession

    service = _metrics_service()
    async with StateSession() as state:
        events = await service.list_events(
            state,
            event_type=event_type,
            user_id=user_id,
            limit=limit,
            offset=offset,
        )
        total = await service.get_event_count(state, event_type=event_type)
        return EventListResponse(
            events=[
                EventResponse(
                    id=e.id,
                    event_type=e.event_type,
                    event_data=e.event_data,
                    user_id=e.user_id,
                    created_at=e.created_at,
                )
                for e in events
            ],
            total=total,
        )


@router.post("/api/admin/metrics/aggregate", response_model=AggregateResponse)
async def aggregate(body: AggregateRequest):
    from ...main import StateSession

    service = _metrics_service()
    async with StateSession() as state:
        metrics = await service.aggregate_metrics(state, body.period_start, body.period_end)
        return AggregateResponse(metrics=metrics)


@router.post("/api/admin/metrics/summaries", response_model=SummaryListResponse)
async def save_summaries(body: AggregateRequest):
    from ...main import StateSession

    service = _metrics_service()
    async with StateSession() as state:
        summaries = await service.save_summaries(state, body.period_start, body.period_end)
        await state.commit()
        return SummaryListResponse(
            summaries=[
                SummaryResponse(
                    id=s.id,
                    period_start=s.period_start,
                    period_end=s.period_end,
                    metric_type=s.metric_type,
                    value=s.value,
                    sample_count=s.sample_count,
                    created_at=s.created_at,
                )
                for s in summaries
            ]
        )


@router.get("/api/admin/metrics/summaries", response_model=SummaryListResponse)
async def list_summaries(
    period_start: str | None = Query(default=None),
    period_end: str | None = Query(default=None),
):
    from ...main import StateSession
    from datetime import datetime

    service = _metrics_service()
    async with StateSession() as state:
        ps = datetime.fromisoformat(period_start) if period_start else None
        pe = datetime.fromisoformat(period_end) if period_end else None
        summaries = await service.get_summaries(state, period_start=ps, period_end=pe)
        return SummaryListResponse(
            summaries=[
                SummaryResponse(
                    id=s.id,
                    period_start=s.period_start,
                    period_end=s.period_end,
                    metric_type=s.metric_type,
                    value=s.value,
                    sample_count=s.sample_count,
                    created_at=s.created_at,
                )
                for s in summaries
            ]
        )


@router.post("/api/admin/metrics/baselines", response_model=BaselineResponse)
async def capture_baseline(body: CaptureBaselineRequest):
    from ...main import StateSession
    import json

    service = _metrics_service()
    async with StateSession() as state:
        baseline = await service.capture_baseline(
            state, body.label, body.period_start, body.period_end
        )
        await state.commit()
        return BaselineResponse(
            id=baseline.id,
            label=baseline.label,
            period_start=baseline.period_start,
            period_end=baseline.period_end,
            summary=json.loads(baseline.summary_json),
            created_at=baseline.created_at,
        )


@router.get("/api/admin/metrics/baselines", response_model=BaselineListResponse)
async def list_baselines():
    from ...main import StateSession

    service = _metrics_service()
    async with StateSession() as state:
        baselines = await service.list_baselines(state)
        return BaselineListResponse(
            baselines=[
                BaselineResponse(
                    id=b.id,
                    label=b.label,
                    period_start=b.period_start,
                    period_end=b.period_end,
                    summary=b.summary,
                    created_at=b.created_at,
                )
                for b in baselines
            ]
        )


@router.post("/api/admin/metrics/compare", response_model=ComparisonResponse)
async def compare(body: CompareRequest):
    from ...main import StateSession

    service = _metrics_service()
    async with StateSession() as state:
        try:
            result = await service.compare_with_baseline(
                state, body.baseline_id, body.current_start, body.current_end
            )
            return ComparisonResponse(
                baseline_id=result.baseline_id,
                baseline_label=result.baseline_label,
                metrics={
                    k: ComparisonMetricEntry(
                        baseline=v["baseline"],
                        current=v["current"],
                        delta=v["delta"],
                    )
                    for k, v in result.metrics.items()
                },
            )
        except Exception as exc:
            raise _translate_error(exc)


@router.post("/api/admin/metrics/purge", response_model=PurgeResponse)
async def purge_events(retention_days: int | None = Query(default=None)):
    from ...main import StateSession

    service = _metrics_service()
    async with StateSession() as state:
        count = await service.purge_old_events(state, retention_days=retention_days)
        await state.commit()
        return PurgeResponse(purged_count=count)