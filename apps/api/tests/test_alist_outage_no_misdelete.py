"""Regression: an AList outage must not mark active indexed resources missing.

During rolling sync, a connection-refused outage from AList must be distinguished
from a successful listing that omits a resource. The outage must fail the scan
item without advancing missing-streak / missing-candidate fields or flipping the
resource status to suspected_missing / missing. Recovery on the next window must
preserve the same resource identity.

Corresponds to the no-misdelete invariant for rolling sync (1.0 dev doc 48/49).
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import search
from cloudsite.database import IndexBase, StateBase
from cloudsite.models import (
    Folder,
    Resource,
    SyncCycle,
    SyncCycleItem,
    SystemSetting,
)
from cloudsite.sync import rolling
from cloudsite.sync.governor import SyncRequestGovernor


async def _factories(monkeypatch):
    state_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    index_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    index_factory = async_sessionmaker(index_engine, expire_on_commit=False)
    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)
    monkeypatch.setattr(rolling, "StateSession", state_factory)
    monkeypatch.setattr(rolling, "IndexSession", index_factory)
    monkeypatch.setattr(search, "StateSession", state_factory)
    monkeypatch.setattr(search, "IndexSession", index_factory)

    async def no_log(*_, **__):
        return None

    monkeypatch.setattr(rolling, "log_operation", no_log)
    return state_engine, index_engine, state_factory, index_factory


async def _bootstrap(monkeypatch, anchor):
    """Create in-memory stores with one active folder and one active resource."""
    state_engine, index_engine, state_factory, index_factory = await _factories(monkeypatch)
    async with index_engine.begin() as conn:
        await conn.exec_driver_sql(
            "CREATE VIRTUAL TABLE search_fts USING fts5("
            "object_id UNINDEXED, object_type UNINDEXED, name, extension, "
            "content_type UNINDEXED, description, tags, breadcrumb_text)"
        )
    async with state_factory() as session:
        session.add_all(
            [
                SystemSetting(key="sync_engine_version", value="1.1"),
                SystemSetting(key="instance_initialized_at", value="2026-08-28T00:00:00+00:00"),
                SystemSetting(key="initial_index_completed_at", value="2026-08-28T01:00:00+00:00"),
            ]
        )
        await session.commit()
    resource_modified = datetime(2026, 8, 29, tzinfo=timezone.utc)
    async with index_factory() as session:
        folder = Folder(
            id="f-root",
            name="software",
            path="/software",
            parent_id=None,
            content_type="software",
            root_mapping_id=1,
            status="active",
        )
        resource = Resource(
            id="r-a",
            name="app.zip",
            path="/software/app.zip",
            parent_id="f-root",
            content_type="software",
            root_mapping_id=1,
            extension="zip",
            mime_type="application/zip",
            size=1024,
            modified_at=resource_modified,
            status="active",
        )
        cycle = SyncCycle(
            status="planned",
            cycle_type="normal",
            anchor_at=anchor,
            planned_folder_count=1,
        )
        session.add_all([folder, resource, cycle])
        await session.flush()
        session.add(SyncCycleItem(cycle_id=cycle.id, folder_id="f-root", folder_path="/software"))
        await session.commit()
    return state_engine, index_engine, state_factory, index_factory


def _resource_entries():
    return [{"name": "app.zip", "is_dir": False, "size": 1024, "modified": "2026-08-29T00:00:00Z"}]


class _WorkingClient:
    """AList provider that returns a fixed listing."""

    def __init__(self, entries):
        self._entries = entries

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def list_path(self, path, refresh=False, strict=False):
        return list(self._entries)


class _ConnectionRefusedClient:
    """AList provider whose listing raises a connection-refused error."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def list_path(self, *_args, **_kwargs):
        raise ConnectionRefusedError("AList connection refused")


async def _no_wait(self):
    self.request_count += 1
    return 0


async def _circuit_closed():
    return {"open": False, "until": None, "reason": "", "failures": 0}


def _install_provider(monkeypatch, client_holder):
    async def fake_load():
        return client_holder["client"], []

    monkeypatch.setattr(rolling, "load_client_and_roots", fake_load)
    monkeypatch.setattr(rolling, "sync_circuit_status", _circuit_closed)
    monkeypatch.setattr(SyncRequestGovernor, "wait_before_request", _no_wait)


async def _latest_item(session, folder_id="f-root"):
    cycle = await session.scalar(select(SyncCycle).order_by(SyncCycle.id.desc()).limit(1))
    item = await session.scalar(
        select(SyncCycleItem).where(
            SyncCycleItem.cycle_id == cycle.id,
            SyncCycleItem.folder_id == folder_id,
        )
    )
    return cycle, item


async def test_alist_outage_does_not_mark_active_resource_missing(monkeypatch):
    """An AList connection-refused outage must not advance missing counters or status.

    Sequence:
      1. Baseline window: provider lists the resource -> resource stays active.
      2. Outage window: provider raises ConnectionRefusedError -> scan item fails
         but the resource remains active with missing_streak=0 and no
         missing_candidate_at / missing_last_observed_cycle_id.
      3. Recovery window: provider lists the resource again -> same resource id
         stays active with no missing evidence.
    """
    anchor = datetime(2026, 8, 30, tzinfo=timezone.utc)
    state_engine, index_engine, state_factory, index_factory = await _bootstrap(monkeypatch, anchor)

    client_holder = {"client": _WorkingClient(_resource_entries())}
    _install_provider(monkeypatch, client_holder)

    # --- Window 1: baseline success, resource confirmed active. ---
    result = await rolling.run_due_rolling_window(manual=True, now=anchor + timedelta(hours=6))
    assert result["status"] == "success"
    async with index_factory() as session:
        resource = await session.get(Resource, "r-a")
        assert resource.status == "active"
        assert resource.missing_streak == 0
        assert resource.missing_candidate_at is None
        assert resource.missing_last_observed_cycle_id is None

    # --- Window 2: AList outage (connection refused), new cycle. ---
    client_holder["client"] = _ConnectionRefusedClient()
    outage_now = anchor + timedelta(hours=24, minutes=1)
    result = await rolling.run_due_rolling_window(manual=True, now=outage_now)
    assert result["status"] in {"failed", "partial"}

    async with index_factory() as session:
        resource = await session.get(Resource, "r-a")
        # Core no-misdelete invariant: outage must not advance deletion evidence.
        assert resource.id == "r-a"
        assert resource.status == "active"
        assert resource.missing_streak == 0
        assert resource.missing_candidate_at is None
        assert resource.missing_last_observed_cycle_id is None
        # The scan item in the latest cycle must be failed, not silently succeeded.
        cycle, item = await _latest_item(session)
        assert cycle.status == "partial"
        assert item.status == "failed"

    # --- Window 3: provider recovery, same partial cycle, resource stays active. ---
    client_holder["client"] = _WorkingClient(_resource_entries())
    recovery_now = outage_now + timedelta(minutes=1)
    result = await rolling.run_due_rolling_window(manual=True, now=recovery_now)
    assert result["status"] == "success"

    async with index_factory() as session:
        resource = await session.get(Resource, "r-a")
        assert resource.id == "r-a"
        assert resource.status == "active"
        assert resource.missing_streak == 0
        assert resource.missing_candidate_at is None
        assert resource.missing_last_observed_cycle_id is None
        cycle, item = await _latest_item(session)
        assert item.status == "success"

    await state_engine.dispose()
    await index_engine.dispose()


async def test_successful_omission_advances_missing_to_distinguish_from_outage(monkeypatch):
    """A successful listing that omits the resource DOES advance missing counters.

    This proves the outage test above is not passing trivially: when AList truly
    reports the resource is gone (empty listing, no error), the missing-streak
    advances as designed, distinguishing provider outage from observed deletion.
    """
    anchor = datetime(2026, 8, 30, tzinfo=timezone.utc)
    state_engine, index_engine, state_factory, index_factory = await _bootstrap(monkeypatch, anchor)

    client_holder = {"client": _WorkingClient(_resource_entries())}
    _install_provider(monkeypatch, client_holder)

    # Baseline: resource is active.
    await rolling.run_due_rolling_window(manual=True, now=anchor + timedelta(hours=6))

    # New cycle: listing succeeds but omits the resource (empty listing).
    client_holder["client"] = _WorkingClient([])
    omission_now = anchor + timedelta(hours=24, minutes=1)
    result = await rolling.run_due_rolling_window(manual=True, now=omission_now)
    assert result["status"] == "success"

    async with index_factory() as session:
        resource = await session.get(Resource, "r-a")
        assert resource.id == "r-a"
        assert resource.status == "suspected_missing"
        assert resource.missing_streak == 1
        assert resource.missing_candidate_at is not None
        assert resource.missing_last_observed_cycle_id is not None

    await state_engine.dispose()
    await index_engine.dispose()
