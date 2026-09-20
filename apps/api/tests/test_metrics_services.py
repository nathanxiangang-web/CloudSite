"""G2 metrics service tests.

Covers: config get/set, event recording, event listing, metrics aggregation,
baseline capture/list, baseline comparison, purge old events, try_record
best-effort, raw query privacy stripping.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from cloudsite.database import StateBase
from cloudsite.models import MetricEvent, SystemSetting
from cloudsite.services import metrics


@pytest.fixture
async def state_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    yield factory
    await engine.dispose()


def _now():
    return datetime.now(timezone.utc)


async def test_get_config_defaults(state_session):
    async with state_session() as state:
        cfg = await metrics.get_config(state)
        assert cfg.enabled is True
        assert cfg.retention_days == 90
        assert cfg.upload_raw_queries is False


async def test_set_config(state_session):
    async with state_session() as state:
        cfg = await metrics.set_config(state, enabled=False, retention_days=30, upload_raw_queries=True)
        await state.commit()
        assert cfg.enabled is False
        assert cfg.retention_days == 30
        assert cfg.upload_raw_queries is True

    async with state_session() as state:
        cfg = await metrics.get_config(state)
        assert cfg.enabled is False
        assert cfg.retention_days == 30
        assert cfg.upload_raw_queries is True


async def test_set_config_invalid_retention(state_session):
    async with state_session() as state:
        with pytest.raises(metrics.MetricsError):
            await metrics.set_config(state, retention_days=0)


async def test_record_event_basic(state_session):
    async with state_session() as state:
        event = await metrics.record_event(state, "download_redirect_issued", {"resource_id": "r1"})
        await state.commit()
        assert event.id.startswith("me_")
        assert event.event_type == "download_redirect_issued"
        assert event.event_data is not None
        assert event.user_id is None


async def test_record_event_with_user(state_session):
    async with state_session() as state:
        event = await metrics.record_event(state, "search_performed", {"result_count": 5}, user_id="u1")
        await state.commit()
        assert event.user_id == "u1"


async def test_record_event_disabled(state_session):
    async with state_session() as state:
        await metrics.set_config(state, enabled=False)
        await state.commit()
        with pytest.raises(metrics.MetricsError):
            await metrics.record_event(state, "test_event")


async def test_record_event_strips_raw_query_by_default(state_session):
    async with state_session() as state:
        event = await metrics.record_event(state, "search_performed", {
            "result_count": 3,
            "raw_query": "sensitive search term",
        })
        await state.commit()
        import json
        data = json.loads(event.event_data)
        assert "raw_query" not in data
        assert data["result_count"] == 3


async def test_record_event_keeps_raw_query_when_enabled(state_session):
    async with state_session() as state:
        await metrics.set_config(state, upload_raw_queries=True)
        await state.commit()
        event = await metrics.record_event(state, "search_performed", {
            "result_count": 3,
            "raw_query": "sensitive search term",
        })
        await state.commit()
        import json
        data = json.loads(event.event_data)
        assert data["raw_query"] == "sensitive search term"


async def test_list_events(state_session):
    async with state_session() as state:
        for i in range(5):
            await metrics.record_event(state, "download_redirect_issued", {"i": i})
        await metrics.record_event(state, "search_performed", {"result_count": 0})
        await state.commit()

        events = await metrics.list_events(state)
        assert len(events) == 6
        assert events[0].event_type in ("download_redirect_issued", "search_performed")

        downloads = await metrics.list_events(state, event_type="download_redirect_issued")
        assert len(downloads) == 5
        assert all(e.event_type == "download_redirect_issued" for e in downloads)


async def test_list_events_pagination(state_session):
    async with state_session() as state:
        for i in range(10):
            await metrics.record_event(state, "test_event", {"i": i})
        await state.commit()

        page1 = await metrics.list_events(state, limit=5, offset=0)
        page2 = await metrics.list_events(state, limit=5, offset=5)
        assert len(page1) == 5
        assert len(page2) == 5
        assert page1[0].id != page2[0].id


async def test_aggregate_metrics(state_session):
    now = _now()
    start = now - timedelta(hours=1)
    async with state_session() as state:
        await metrics.record_event(state, metrics.EVENT_DOWNLOAD_REDIRECT, {"resource_id": "r1"})
        await metrics.record_event(state, metrics.EVENT_DOWNLOAD_REDIRECT, {"resource_id": "r2"})
        await metrics.record_event(state, metrics.EVENT_SEARCH_PERFORMED, {"result_count": 5})
        await metrics.record_event(state, metrics.EVENT_SEARCH_PERFORMED, {"result_count": 0})
        await metrics.record_event(state, metrics.EVENT_RESOURCE_SELECTED, {"success": True})
        await metrics.record_event(state, metrics.EVENT_RESOURCE_SELECTED, {"success": False})
        await state.commit()

        result = await metrics.aggregate_metrics(state, start, now + timedelta(hours=1))
        assert result[metrics.METRIC_DOWNLOAD_REDIRECT_COUNT] == 2.0
        assert result[metrics.METRIC_SEARCH_HIT_RATE] == 0.5
        assert result[metrics.METRIC_NO_RESULT_RATE] == 0.5
        assert result[metrics.METRIC_RESOURCE_SELECTION_SUCCESS_RATE] == 0.5


async def test_aggregate_metrics_empty(state_session):
    now = _now()
    async with state_session() as state:
        result = await metrics.aggregate_metrics(state, now - timedelta(hours=1), now)
        assert result[metrics.METRIC_DOWNLOAD_REDIRECT_COUNT] == 0.0
        assert result[metrics.METRIC_SEARCH_HIT_RATE] == 0.0
        assert result[metrics.METRIC_RESOURCE_SELECTION_SUCCESS_RATE] == 0.0


async def test_aggregate_organize_time(state_session):
    now = _now()
    start = now - timedelta(hours=1)
    async with state_session() as state:
        await metrics.record_event(state, metrics.EVENT_ORGANIZE_BATCH_COMPLETED, {
            "elapsed_ms": 60000, "item_count": 200,
        })
        await metrics.record_event(state, metrics.EVENT_ORGANIZE_BATCH_COMPLETED, {
            "elapsed_ms": 30000, "item_count": 100,
        })
        await state.commit()

        result = await metrics.aggregate_metrics(state, start, now + timedelta(hours=1))
        assert result[metrics.METRIC_ORGANIZE_TIME_PER_100] == 30000.0


async def test_aggregate_site_setup_time(state_session):
    now = _now()
    start = now - timedelta(hours=1)
    async with state_session() as state:
        await metrics.record_event(state, metrics.EVENT_SITE_SETUP_COMPLETED, {"elapsed_ms": 5000})
        await metrics.record_event(state, metrics.EVENT_SITE_SETUP_COMPLETED, {"elapsed_ms": 3000})
        await state.commit()

        result = await metrics.aggregate_metrics(state, start, now + timedelta(hours=1))
        assert result[metrics.METRIC_FIRST_SITE_SETUP_TIME] == 4000.0


async def test_save_summaries(state_session):
    now = _now()
    start = now - timedelta(hours=1)
    async with state_session() as state:
        await metrics.record_event(state, metrics.EVENT_DOWNLOAD_REDIRECT, {})
        await state.commit()
        summaries = await metrics.save_summaries(state, start, now + timedelta(hours=1))
        await state.commit()
        assert len(summaries) > 0
        assert all(s.id.startswith("ms_") for s in summaries)


async def test_get_summaries(state_session):
    now = _now()
    start = now - timedelta(hours=1)
    async with state_session() as state:
        await metrics.save_summaries(state, start, now + timedelta(hours=1))
        await state.commit()
        summaries = await metrics.get_summaries(state)
        assert len(summaries) > 0


async def test_capture_baseline(state_session):
    now = _now()
    start = now - timedelta(hours=1)
    async with state_session() as state:
        await metrics.record_event(state, metrics.EVENT_DOWNLOAD_REDIRECT, {})
        await state.commit()
        baseline = await metrics.capture_baseline(state, "pre-v1.3", start, now + timedelta(hours=1))
        await state.commit()
        assert baseline.id.startswith("mb_")
        assert baseline.label == "pre-v1.3"
        import json
        summary = json.loads(baseline.summary_json)
        assert metrics.METRIC_DOWNLOAD_REDIRECT_COUNT in summary


async def test_list_baselines(state_session):
    now = _now()
    start = now - timedelta(hours=1)
    async with state_session() as state:
        await metrics.capture_baseline(state, "baseline-1", start, now)
        await metrics.capture_baseline(state, "baseline-2", start, now)
        await state.commit()
        baselines = await metrics.list_baselines(state)
        assert len(baselines) == 2
        assert baselines[0].label in ("baseline-1", "baseline-2")


async def test_compare_with_baseline(state_session):
    now = _now()
    start = now - timedelta(hours=2)
    mid = now - timedelta(hours=1)
    async with state_session() as state:
        old_event = metrics.MetricEvent(
            id=metrics._new_id(metrics.EVENT_ID_PREFIX),
            event_type=metrics.EVENT_DOWNLOAD_REDIRECT,
            event_data='{}',
            user_id=None,
            created_at=start + timedelta(minutes=30),
        )
        state.add(old_event)
        await state.commit()
        baseline = await metrics.capture_baseline(state, "pre", start, mid)
        await state.commit()

        await metrics.record_event(state, metrics.EVENT_DOWNLOAD_REDIRECT, {})
        await metrics.record_event(state, metrics.EVENT_DOWNLOAD_REDIRECT, {})
        await state.commit()

        result = await metrics.compare_with_baseline(state, baseline.id, mid, now + timedelta(hours=1))
        assert result.baseline_label == "pre"
        dl_metric = result.metrics[metrics.METRIC_DOWNLOAD_REDIRECT_COUNT]
        assert dl_metric["baseline"] == 1.0
        assert dl_metric["current"] == 2.0
        assert dl_metric["delta"] == 1.0


async def test_compare_baseline_not_found(state_session):
    now = _now()
    async with state_session() as state:
        with pytest.raises(metrics.BaselineNotFound):
            await metrics.compare_with_baseline(state, "mb_nonexistent", now - timedelta(hours=1), now)


async def test_purge_old_events(state_session):
    async with state_session() as state:
        old_event = metrics.MetricEvent(
            id=metrics._new_id(metrics.EVENT_ID_PREFIX),
            event_type="old_event",
            event_data=None,
            user_id=None,
            created_at=_now() - timedelta(days=100),
        )
        state.add(old_event)
        await metrics.record_event(state, "recent_event")
        await state.commit()

        purged = await metrics.purge_old_events(state, retention_days=30)
        await state.commit()
        assert purged == 1

        events = await metrics.list_events(state)
        assert len(events) == 1
        assert events[0].event_type == "recent_event"


async def test_purge_uses_config_retention(state_session):
    async with state_session() as state:
        await metrics.set_config(state, retention_days=1)
        await state.commit()
        old_event = metrics.MetricEvent(
            id=metrics._new_id(metrics.EVENT_ID_PREFIX),
            event_type="old_event",
            event_data=None,
            user_id=None,
            created_at=_now() - timedelta(days=2),
        )
        state.add(old_event)
        await state.commit()

        purged = await metrics.purge_old_events(state)
        await state.commit()
        assert purged == 1


async def test_try_record_never_raises(state_session):
    async with state_session() as state:
        await metrics.set_config(state, enabled=False)
        await state.commit()
        await metrics.try_record(state, "test_event", {"key": "value"})


async def test_try_record_records_when_enabled(state_session):
    async with state_session() as state:
        await metrics.try_record(state, "test_event", {"key": "value"})
        await state.commit()
        events = await metrics.list_events(state)
        assert len(events) == 1
        assert events[0].event_type == "test_event"


async def test_get_event_count(state_session):
    async with state_session() as state:
        await metrics.record_event(state, "type_a")
        await metrics.record_event(state, "type_b")
        await metrics.record_event(state, "type_a")
        await state.commit()
        assert await metrics.get_event_count(state) == 3
        assert await metrics.get_event_count(state, event_type="type_a") == 2