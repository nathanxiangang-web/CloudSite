"""G2 metrics admin route end-to-end tests.

Covers: config get/update, event record/list, aggregate, summaries,
baseline capture/list, compare, purge, admin auth required.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import auth, main
from cloudsite.database import IndexBase, StateBase
from cloudsite.models import SiteSettings, SystemSetting, utcnow

ORIGIN = {"Origin": "http://testserver"}


def _admin_cookies():
    return {main.SESSION_COOKIE: main.create_session_token("admin")}


async def _setup(monkeypatch):
    state_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    index_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    index_factory = async_sessionmaker(index_engine, expire_on_commit=False)
    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)
    monkeypatch.setattr(main, "StateSession", state_factory)
    monkeypatch.setattr(auth, "StateSession", state_factory)
    monkeypatch.setattr(main, "IndexSession", index_factory)

    async with state_factory() as state:
        state.add(SiteSettings(id=1))
        state.add(SystemSetting(key="setup_completed", value="true", value_type="string"))
        await state.commit()

    transport = httpx.ASGITransport(app=main.app)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    return client, state_factory


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _past_iso(hours=1):
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


async def test_get_config(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        resp = await client.get("/api/admin/metrics/config", headers=ORIGIN, cookies=_admin_cookies())
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert data["retention_days"] == 90
        assert data["upload_raw_queries"] is False
    finally:
        await client.aclose()


async def test_update_config(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        resp = await client.put("/api/admin/metrics/config", json={
            "enabled": False,
            "retention_days": 30,
            "upload_raw_queries": True,
        }, headers=ORIGIN, cookies=_admin_cookies())
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is False
        assert data["retention_days"] == 30
        assert data["upload_raw_queries"] is True
    finally:
        await client.aclose()


async def test_record_event(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        resp = await client.post("/api/admin/metrics/events", json={
            "event_type": "download_redirect_issued",
            "event_data": {"resource_id": "r1"},
        }, headers=ORIGIN, cookies=_admin_cookies())
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"].startswith("me_")
        assert data["event_type"] == "download_redirect_issued"
    finally:
        await client.aclose()


async def test_list_events(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        for i in range(3):
            await client.post("/api/admin/metrics/events", json={
                "event_type": "test_event",
                "event_data": {"i": i},
            }, headers=ORIGIN, cookies=_admin_cookies())

        resp = await client.get("/api/admin/metrics/events", headers=ORIGIN, cookies=_admin_cookies())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["events"]) == 3
        assert data["total"] == 3
    finally:
        await client.aclose()


async def test_list_events_filter_by_type(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        await client.post("/api/admin/metrics/events", json={"event_type": "type_a"}, headers=ORIGIN, cookies=_admin_cookies())
        await client.post("/api/admin/metrics/events", json={"event_type": "type_b"}, headers=ORIGIN, cookies=_admin_cookies())

        resp = await client.get("/api/admin/metrics/events?event_type=type_a", headers=ORIGIN, cookies=_admin_cookies())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["events"]) == 1
        assert data["events"][0]["event_type"] == "type_a"
    finally:
        await client.aclose()


async def test_aggregate(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        await client.post("/api/admin/metrics/events", json={
            "event_type": "download_redirect_issued",
            "event_data": {"resource_id": "r1"},
        }, headers=ORIGIN, cookies=_admin_cookies())

        resp = await client.post("/api/admin/metrics/aggregate", json={
            "period_start": _past_iso(2),
            "period_end": _now_iso(),
        }, headers=ORIGIN, cookies=_admin_cookies())
        assert resp.status_code == 200
        data = resp.json()
        assert "download_redirect_count" in data["metrics"]
    finally:
        await client.aclose()


async def test_save_summaries(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        resp = await client.post("/api/admin/metrics/summaries", json={
            "period_start": _past_iso(2),
            "period_end": _now_iso(),
        }, headers=ORIGIN, cookies=_admin_cookies())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["summaries"]) > 0
    finally:
        await client.aclose()


async def test_list_summaries(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        await client.post("/api/admin/metrics/summaries", json={
            "period_start": _past_iso(2),
            "period_end": _now_iso(),
        }, headers=ORIGIN, cookies=_admin_cookies())

        resp = await client.get("/api/admin/metrics/summaries", headers=ORIGIN, cookies=_admin_cookies())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["summaries"]) > 0
    finally:
        await client.aclose()


async def test_capture_baseline(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        resp = await client.post("/api/admin/metrics/baselines", json={
            "label": "pre-v1.3",
            "period_start": _past_iso(2),
            "period_end": _now_iso(),
        }, headers=ORIGIN, cookies=_admin_cookies())
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"].startswith("mb_")
        assert data["label"] == "pre-v1.3"
    finally:
        await client.aclose()


async def test_list_baselines(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        await client.post("/api/admin/metrics/baselines", json={
            "label": "baseline-1",
            "period_start": _past_iso(2),
            "period_end": _now_iso(),
        }, headers=ORIGIN, cookies=_admin_cookies())

        resp = await client.get("/api/admin/metrics/baselines", headers=ORIGIN, cookies=_admin_cookies())
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["baselines"]) == 1
        assert data["baselines"][0]["label"] == "baseline-1"
    finally:
        await client.aclose()


async def test_compare(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        resp = await client.post("/api/admin/metrics/baselines", json={
            "label": "pre",
            "period_start": _past_iso(2),
            "period_end": _past_iso(1),
        }, headers=ORIGIN, cookies=_admin_cookies())
        baseline_id = resp.json()["id"]

        await client.post("/api/admin/metrics/events", json={
            "event_type": "download_redirect_issued",
            "event_data": {"resource_id": "r1"},
        }, headers=ORIGIN, cookies=_admin_cookies())

        resp = await client.post("/api/admin/metrics/compare", json={
            "baseline_id": baseline_id,
            "current_start": _past_iso(1),
            "current_end": _now_iso(),
        }, headers=ORIGIN, cookies=_admin_cookies())
        assert resp.status_code == 200
        data = resp.json()
        assert data["baseline_label"] == "pre"
        assert "download_redirect_count" in data["metrics"]
    finally:
        await client.aclose()


async def test_compare_not_found(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        resp = await client.post("/api/admin/metrics/compare", json={
            "baseline_id": "mb_nonexistent",
            "current_start": _past_iso(1),
            "current_end": _now_iso(),
        }, headers=ORIGIN, cookies=_admin_cookies())
        assert resp.status_code == 404
    finally:
        await client.aclose()


async def test_purge(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        resp = await client.post("/api/admin/metrics/purge", headers=ORIGIN, cookies=_admin_cookies())
        assert resp.status_code == 200
        data = resp.json()
        assert "purged_count" in data
    finally:
        await client.aclose()


async def test_admin_auth_required(monkeypatch):
    client, _ = await _setup(monkeypatch)
    try:
        resp = await client.get("/api/admin/metrics/config", headers=ORIGIN)
        assert resp.status_code == 403
    finally:
        await client.aclose()