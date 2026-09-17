"""Focused route tests for G2 metrics persistence on public search and download.

Covers:
- A successful public search leaves a committed MetricEvent row.
- A successful download redirect leaves a committed MetricEvent row.
- A metrics storage error leaves the public search response intact.
- A metrics storage error leaves the public download response intact.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import auth, main
from cloudsite.database import IndexBase, StateBase
from cloudsite.download import DownloadResolution
from cloudsite.download_rate_limit import DownloadRateDecision
from cloudsite.models import (
    AListConnection,
    ContentRootMapping,
    MetricEvent,
    Resource,
    SystemSetting,
    User,
    utcnow,
)
from cloudsite.sessions import USER_SESSION_COOKIE, create_user_session


_SEARCH_FTS_DDL = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5("
    "object_id UNINDEXED, object_type UNINDEXED, name, extension, "
    "content_type UNINDEXED, description, tags, breadcrumb_text)"
)


async def _bootstrap(tmp_path):
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)
        await conn.exec_driver_sql(_SEARCH_FTS_DDL)
    state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    index_factory = async_sessionmaker(index_engine, expire_on_commit=False)
    return state_engine, index_engine, state_factory, index_factory


def _patch_sessions(monkeypatch, state_factory, index_factory):
    monkeypatch.setattr(main, "StateSession", state_factory)
    monkeypatch.setattr(main, "IndexSession", index_factory)
    monkeypatch.setattr(auth, "StateSession", state_factory)


async def _seed_user(state_factory):
    async with state_factory() as state:
        state.add(SystemSetting(key="setup_completed", value="true", value_type="string"))
        user = User(
            username="reader", username_normalized="reader", password_hash="x",
            status="active", created_at=utcnow(), updated_at=utcnow(),
        )
        state.add(user)
        await state.flush()
        _, user_token = await create_user_session(state, user.id, utcnow())
        await state.commit()
    return user_token


async def _seed_search_fixture(state_factory, index_factory):
    async with state_factory() as state:
        state.add(ContentRootMapping(
            id=1, content_type="software", display_name="Software",
            alist_path="/software", enabled=True,
        ))
        await state.commit()
    async with index_factory() as index:
        index.add(Resource(
            id="r-metrics-search", name="metrics-tool.zip",
            path="/software/metrics-tool.zip", parent_id=None,
            content_type="software", root_mapping_id=1, extension="zip",
            status="active", indexed_at=datetime.now(timezone.utc),
        ))
        await index.execute(text(
            "INSERT INTO search_fts(object_id, object_type, name, extension, "
            "content_type, description, tags, breadcrumb_text) "
            "VALUES ('r-metrics-search', 'resource', 'metrics-tool.zip', 'zip', "
            "'software', '', '', '/software/metrics-tool.zip')"
        ))
        await index.commit()


async def _seed_download_fixture(state_factory, index_factory):
    async with state_factory() as state:
        state.add(AListConnection(id=1, name="local", base_url="http://alist.local", enabled=True))
        state.add(ContentRootMapping(
            id=1, content_type="software", display_name="Software",
            alist_path="/software", enabled=True,
        ))
        await state.commit()
    async with index_factory() as index:
        index.add(Resource(
            id="r-metrics-download", name="metrics-file.zip",
            path="/software/metrics-file.zip", parent_id=None,
            content_type="software", root_mapping_id=1, extension="zip",
            status="active", indexed_at=datetime.now(timezone.utc),
        ))
        await index.commit()


def _allow_download(monkeypatch, url="https://download.example/metrics-file.zip"):
    async def _fake_resolve(resource, connection):
        return DownloadResolution(url=url, target_host="download.example", base_path="/software", has_sign=True, steps=[])

    async def _fake_rate(address, now=None):
        return DownloadRateDecision(allowed=True)

    monkeypatch.setattr("cloudsite.routers.downloads.resolve_download_entry", _fake_resolve)
    monkeypatch.setattr("cloudsite.routers.downloads.check_download_rate", _fake_rate)
    return url


def _authed_client(transport, user_token):
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    client.cookies.set(USER_SESSION_COOKIE, user_token)
    return client


async def test_search_persists_metric_event(tmp_path, monkeypatch):
    state_engine, index_engine, state_factory, index_factory = await _bootstrap(tmp_path)
    user_token = await _seed_user(state_factory)
    await _seed_search_fixture(state_factory, index_factory)
    _patch_sessions(monkeypatch, state_factory, index_factory)

    transport = httpx.ASGITransport(app=main.app)
    try:
        async with _authed_client(transport, user_token) as client:
            resp = await client.get("/api/search?q=metrics-tool")
            assert resp.status_code == 200, resp.text
            assert resp.json()["total"] >= 1

        async with state_factory() as state:
            events = list((
                await state.scalars(
                    select(MetricEvent).where(MetricEvent.event_type == "search_performed")
                )
            ).all())
            assert len(events) == 1, "expected one committed search_performed metric event"
            assert events[0].event_type == "search_performed"
    finally:
        await state_engine.dispose()
        await index_engine.dispose()


async def test_download_persists_metric_event(tmp_path, monkeypatch):
    state_engine, index_engine, state_factory, index_factory = await _bootstrap(tmp_path)
    user_token = await _seed_user(state_factory)
    await _seed_download_fixture(state_factory, index_factory)
    _patch_sessions(monkeypatch, state_factory, index_factory)
    expected_url = _allow_download(monkeypatch)

    transport = httpx.ASGITransport(app=main.app)
    try:
        async with _authed_client(transport, user_token) as client:
            resp = await client.get("/d/r-metrics-download")
            assert resp.status_code == 302, resp.text
            assert resp.headers["location"] == expected_url

        async with state_factory() as state:
            events = list((
                await state.scalars(
                    select(MetricEvent).where(MetricEvent.event_type == "download_redirect_issued")
                )
            ).all())
            assert len(events) == 1, "expected one committed download_redirect_issued metric event"
            assert events[0].event_type == "download_redirect_issued"
    finally:
        await state_engine.dispose()
        await index_engine.dispose()


async def test_search_response_intact_when_metrics_fails(tmp_path, monkeypatch):
    state_engine, index_engine, state_factory, index_factory = await _bootstrap(tmp_path)
    user_token = await _seed_user(state_factory)
    await _seed_search_fixture(state_factory, index_factory)
    _patch_sessions(monkeypatch, state_factory, index_factory)

    async def _raising_record(*_args, **_kwargs):
        raise RuntimeError("simulated metrics storage failure")

    monkeypatch.setattr("cloudsite.services.metrics.record_event", _raising_record)

    transport = httpx.ASGITransport(app=main.app)
    try:
        async with _authed_client(transport, user_token) as client:
            resp = await client.get("/api/search?q=metrics-tool")
            assert resp.status_code == 200, resp.text
            assert resp.json()["total"] >= 1

        async with state_factory() as state:
            count = await state.scalar(select(func.count(MetricEvent.id)))
            assert count == 0, "no metric event should be committed when storage fails"
    finally:
        await state_engine.dispose()
        await index_engine.dispose()


async def test_download_response_intact_when_metrics_fails(tmp_path, monkeypatch):
    state_engine, index_engine, state_factory, index_factory = await _bootstrap(tmp_path)
    user_token = await _seed_user(state_factory)
    await _seed_download_fixture(state_factory, index_factory)
    _patch_sessions(monkeypatch, state_factory, index_factory)
    expected_url = _allow_download(monkeypatch)

    async def _raising_record(*_args, **_kwargs):
        raise RuntimeError("simulated metrics storage failure")

    monkeypatch.setattr("cloudsite.services.metrics.record_event", _raising_record)

    transport = httpx.ASGITransport(app=main.app)
    try:
        async with _authed_client(transport, user_token) as client:
            resp = await client.get("/d/r-metrics-download")
            assert resp.status_code == 302, resp.text
            assert resp.headers["location"] == expected_url

        async with state_factory() as state:
            count = await state.scalar(select(func.count(MetricEvent.id)))
            assert count == 0, "no metric event should be committed when storage fails"
    finally:
        await state_engine.dispose()
        await index_engine.dispose()
