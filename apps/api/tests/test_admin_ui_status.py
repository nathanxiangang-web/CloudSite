"""R1 supplement: Admin UI sync status contract (V2 doc sections 69-70).

V2 section 69: After concurrent scanning there is no unique current_path.
The Admin UI must expose:
    active_workers
    directories_done
    known_pending
    entries_discovered
    recent_paths   (a list, not a single current_path string)

V2 section 70: BFS scanning cannot know the future directory total in
advance, so the UI must not derive or expose a fake percentage. In
particular the contract must not expose a ``percentage``/``progress`` field
nor a (categories_done, categories_total) pair that the client could divide
into a percentage.

These are specification tests against the ``/api/admin/sync/status``
contract that the Admin UI consumes. They document the V2 required shape;
the endpoint is expected to satisfy them once the concurrent-scan status
work lands. No source file is modified by this task.
"""
from __future__ import annotations

import json

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import auth, main
from cloudsite.database import IndexBase, StateBase
from cloudsite.models import SiteSettings, SystemSetting

ORIGIN = {"Origin": "http://testserver"}

# A reasonable upper bound for the recent_paths ring buffer. The concrete
# limit is owned by the endpoint; this test only asserts that some finite
# bound exists so the UI cannot grow an unbounded list.
RECENT_PATHS_MAX_BOUND = 64


def _admin_cookies() -> dict[str, str]:
    return {main.SESSION_COOKIE: main.create_session_token("admin")}


async def _setup(monkeypatch, *, progress: dict | None = None):
    """Build an in-memory app with optional v2_sync_progress payload."""
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
        state.add(
            SystemSetting(
                key="setup_completed", value="true", value_type="string"
            )
        )
        if progress is not None:
            state.add(
                SystemSetting(
                    key="v2_sync_progress",
                    value=json.dumps(progress),
                    value_type="string",
                )
            )
        await state.commit()

    transport = httpx.ASGITransport(app=main.app)
    client = httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    )
    return client, state_factory, state_engine, index_engine


async def _status(client: httpx.AsyncClient) -> dict:
    resp = await client.get(
        "/api/admin/sync/status", headers=ORIGIN, cookies=_admin_cookies()
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# V2 section 69: status field contract
# ---------------------------------------------------------------------------


async def test_status_has_active_workers(monkeypatch):
    client, _, se, ie = await _setup(monkeypatch)
    try:
        data = await _status(client)
        assert "active_workers" in data, (
            "V2 section 69: sync status must expose active_workers "
            "(concurrent scan has no unique current_path)"
        )
        assert isinstance(data["active_workers"], int)
    finally:
        await client.aclose()
        await se.dispose()
        await ie.dispose()


async def test_status_has_directories_done(monkeypatch):
    client, _, se, ie = await _setup(monkeypatch)
    try:
        data = await _status(client)
        assert "directories_done" in data, (
            "V2 section 69: sync status must expose directories_done"
        )
        assert isinstance(data["directories_done"], int)
    finally:
        await client.aclose()
        await se.dispose()
        await ie.dispose()


async def test_status_has_known_pending(monkeypatch):
    client, _, se, ie = await _setup(monkeypatch)
    try:
        data = await _status(client)
        assert "known_pending" in data, (
            "V2 section 69: sync status must expose known_pending "
            "(currently known pending dirs, not a future total)"
        )
        assert isinstance(data["known_pending"], int)
    finally:
        await client.aclose()
        await se.dispose()
        await ie.dispose()


async def test_status_has_entries_discovered(monkeypatch):
    client, _, se, ie = await _setup(monkeypatch)
    try:
        data = await _status(client)
        assert "entries_discovered" in data, (
            "V2 section 69: sync status must expose entries_discovered"
        )
        assert isinstance(data["entries_discovered"], int)
    finally:
        await client.aclose()
        await se.dispose()
        await ie.dispose()


async def test_status_has_recent_paths(monkeypatch):
    client, _, se, ie = await _setup(monkeypatch)
    try:
        data = await _status(client)
        assert "recent_paths" in data, (
            "V2 section 69: sync status must expose recent_paths as a list "
            "(replaces single current_path)"
        )
        assert isinstance(data["recent_paths"], list), (
            "recent_paths must be a list, not a single string"
        )
    finally:
        await client.aclose()
        await se.dispose()
        await ie.dispose()


# ---------------------------------------------------------------------------
# V2 section 70: fake percentage prohibition
# ---------------------------------------------------------------------------


async def test_no_percentage_field(monkeypatch):
    client, _, se, ie = await _setup(monkeypatch)
    try:
        data = await _status(client)
        forbidden = {
            "percentage",
            "percent",
            "progress_percent",
            "progress_percentage",
            "progress",
            "completion",
            "completed_percent",
        }
        present = forbidden & set(data)
        assert not present, (
            f"V2 section 70: status must not expose a fake percentage "
            f"field, found: {sorted(present)}"
        )
    finally:
        await client.aclose()
        await se.dispose()
        await ie.dispose()


async def test_no_derivable_percentage(monkeypatch):
    client, _, se, ie = await _setup(monkeypatch)
    try:
        data = await _status(client)
        # V2 section 70: BFS cannot know the future directory total, so the
        # contract must not expose a (done, total) pair that a client could
        # divide into a percentage. directories_done is allowed (it is a
        # observed count), but a total/known-pending-as-total pair that
        # implies completion ratio is not.
        forbidden_total_keys = {
            "categories_total",
            "directories_total",
            "total_directories",
            "roots_total",
        }
        present = forbidden_total_keys & set(data)
        assert not present, (
            "V2 section 70: status must not expose a directory total that "
            f"would let the UI derive a fake percentage, found: {sorted(present)}"
        )
    finally:
        await client.aclose()
        await se.dispose()
        await ie.dispose()


async def test_current_path_is_list(monkeypatch):
    client, _, se, ie = await _setup(monkeypatch)
    try:
        data = await _status(client)
        # V2 section 69: a single current_path string must not be used to
        # impersonate the whole scan position. If the field is retained for
        # back-compat it must be a list; the canonical field is recent_paths.
        if "current_path" in data:
            assert isinstance(data["current_path"], list), (
                "V2 section 69: current_path must be a list (recent_paths), "
                "not a single string"
            )
        assert "recent_paths" in data, (
            "V2 section 69: recent_paths (list) is the canonical field "
            "replacing single-string current_path"
        )
        assert isinstance(data["recent_paths"], list)
    finally:
        await client.aclose()
        await se.dispose()
        await ie.dispose()


# ---------------------------------------------------------------------------
# Concurrent state correctness
# ---------------------------------------------------------------------------


async def test_active_workers_zero_when_idle(monkeypatch):
    client, _, se, ie = await _setup(monkeypatch)
    try:
        data = await _status(client)
        assert data.get("active_workers") == 0, (
            "idle sync must report active_workers == 0"
        )
    finally:
        await client.aclose()
        await se.dispose()
        await ie.dispose()


async def test_active_workers_positive_when_running(monkeypatch):
    progress = {
        "status": "running",
        "active_workers": 2,
        "directories_done": 3,
        "known_pending": 5,
        "entries_discovered": 42,
        "recent_paths": ["/a", "/b"],
    }
    client, _, se, ie = await _setup(monkeypatch, progress=progress)
    try:
        data = await _status(client)
        assert data.get("active_workers", 0) > 0, (
            "V2 section 69: a running concurrent scan must report "
            "active_workers > 0"
        )
    finally:
        await client.aclose()
        await se.dispose()
        await ie.dispose()


async def test_recent_paths_max_length(monkeypatch):
    progress = {
        "status": "running",
        "recent_paths": [f"/dir/{i}" for i in range(RECENT_PATHS_MAX_BOUND)],
    }
    client, _, se, ie = await _setup(monkeypatch, progress=progress)
    try:
        data = await _status(client)
        assert "recent_paths" in data
        assert isinstance(data["recent_paths"], list)
        assert len(data["recent_paths"]) <= RECENT_PATHS_MAX_BOUND, (
            "V2 section 69: recent_paths must be a bounded ring buffer, "
            f"got length {len(data['recent_paths'])}"
        )
    finally:
        await client.aclose()
        await se.dispose()
        await ie.dispose()
