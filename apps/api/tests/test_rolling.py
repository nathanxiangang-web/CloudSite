from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.database import IndexBase, StateBase
from cloudsite.models import (
    ContentRootMapping,
    Folder,
    FolderScanState,
    Resource,
    SyncCycle,
    SyncCycleItem,
    SyncRun,
    SystemSetting,
)
from cloudsite.sync import rolling
from cloudsite.sync.governor import SyncRequestGovernor
from cloudsite.sync.planner import (
    calculate_window_target,
    next_cycle_anchor,
    next_window_due_at,
)


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    async def sleep(self, seconds: float):
        self.now += seconds


def test_window_target_uses_remaining_div_remaining_windows_without_cap():
    assert calculate_window_target(400, 0) == 100
    assert calculate_window_target(320, 1) == 107
    assert calculate_window_target(1200, 0) == 300
    assert calculate_window_target(2000, 3) == 2000


def test_windows_are_anchored_every_six_hours_and_cycle_is_24_hours():
    anchor = datetime(2026, 8, 30, tzinfo=timezone.utc)
    assert next_window_due_at(anchor, 0) == anchor + timedelta(hours=6)
    assert next_window_due_at(anchor, 3) == anchor + timedelta(hours=24)
    assert next_cycle_anchor(anchor) == anchor + timedelta(hours=24)


def test_governor_prefers_default_five_to_fifteen_seconds_for_normal_scale():
    clock = FakeClock()
    governor = SyncRequestGovernor(target_count=400, clock=clock, sleeper=clock.sleep)
    assert governor.delay_range() == (5.0, 15.0)


def test_governor_reduces_delay_for_large_target_but_never_exceeds_two_rps():
    clock = FakeClock()
    governor = SyncRequestGovernor(target_count=20_000, clock=clock, sleeper=clock.sleep)
    low, high = governor.delay_range()
    assert 0.5 <= low <= high < 5.0


async def test_governor_uses_fake_clock_and_rate_limits_retries_too():
    clock = FakeClock()
    governor = SyncRequestGovernor(
        target_count=20_000,
        clock=clock,
        sleeper=clock.sleep,
        random_uniform=lambda low, _: low,
    )
    assert await governor.wait_before_request() == 0
    second_delay = await governor.wait_before_request()
    assert second_delay >= 0.5
    assert clock.now == second_delay
    assert governor.request_count == 2


def test_scope_validation_rejects_duplicate_paths_and_negative_sizes():
    duplicate = [
        {"name": "A", "is_dir": True},
        {"name": "A", "is_dir": False},
    ]
    try:
        rolling.validate_scope_entries("/软件", duplicate)
        assert False, "duplicate paths must fail"
    except ValueError as exc:
        assert "重复" in str(exc)

    try:
        rolling.validate_scope_entries("/软件", [{"name": "A", "is_dir": False, "size": -1}])
        assert False, "negative sizes must fail"
    except ValueError as exc:
        assert "负数" in str(exc)


def test_fingerprint_uses_direct_stable_metadata_only():
    first = rolling.validate_scope_entries(
        "/软件",
        [{"name": "A.zip", "is_dir": False, "size": 10, "modified": "2026-08-30T00:00:00Z", "raw_url": "one"}],
    )
    second = rolling.validate_scope_entries(
        "/软件",
        [{"name": "A.zip", "is_dir": False, "size": 10, "modified": "2026-08-30T00:00:00Z", "raw_url": "two"}],
    )
    assert rolling.scope_fingerprint(first) == rolling.scope_fingerprint(second)


def test_missing_streak_advances_only_once_in_same_cycle():
    row = SimpleNamespace(
        status="active",
        missing_streak=0,
        missing_candidate_at=None,
        indexed_at=None,
        missing_last_observed_cycle_id=None,
    )
    now = datetime.now(timezone.utc)
    assert rolling._observe_missing_in_cycle(row, 10, now) is False
    assert row.missing_streak == 1
    assert rolling._observe_missing_in_cycle(row, 10, now) is False
    assert row.missing_streak == 1
    assert rolling._observe_missing_in_cycle(row, 11, now) is True
    assert row.status == "missing"


async def _factories(monkeypatch):
    state_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    index_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    index_factory = async_sessionmaker(index_engine, expire_on_commit=False)
    async with state_engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as connection:
        await connection.run_sync(IndexBase.metadata.create_all)
    monkeypatch.setattr(rolling, "StateSession", state_factory)
    monkeypatch.setattr(rolling, "IndexSession", index_factory)

    async def no_log(*_, **__):
        return None

    monkeypatch.setattr(rolling, "log_operation", no_log)
    return state_engine, index_engine, state_factory, index_factory


async def test_migration_requires_completed_first_sync_and_never_bootstraps(monkeypatch):
    state_engine, index_engine, state_factory, index_factory = await _factories(monkeypatch)
    async with index_factory() as session:
        session.add(
            Folder(
                id="f-root",
                name="软件",
                path="/软件",
                parent_id=None,
                content_type="software",
                root_mapping_id=1,
                status="active",
            )
        )
        await session.commit()

    assert await rolling.migrate_existing_index_to_rolling() is False
    async with index_factory() as session:
        assert int(await session.scalar(select(func.count()).select_from(SyncCycle)) or 0) == 0
    async with state_factory() as session:
        assert await session.get(SystemSetting, "sync_engine_version") is None
    await state_engine.dispose()
    await index_engine.dispose()


async def test_v10_to_v11_migration_preserves_index_and_creates_one_cycle(monkeypatch):
    state_engine, index_engine, state_factory, index_factory = await _factories(monkeypatch)
    finished = datetime(2026, 8, 30, 1, 0, tzinfo=timezone.utc)
    anchor = datetime(2026, 8, 30, 2, 0, tzinfo=timezone.utc)
    async with index_factory() as session:
        session.add_all(
            [
                Folder(id="f-root", name="软件", path="/软件", parent_id=None, content_type="software", root_mapping_id=1, status="active"),
                Folder(id="f-child", name="工具", path="/软件/工具", parent_id="f-root", content_type="software", root_mapping_id=1, depth=1, status="active"),
                SyncRun(sync_type="manual", status="success", started_at=finished - timedelta(minutes=5), finished_at=finished),
            ]
        )
        await session.commit()

    assert await rolling.migrate_existing_index_to_rolling(anchor) is True
    assert await rolling.migrate_existing_index_to_rolling(anchor + timedelta(minutes=1)) is True
    async with index_factory() as session:
        assert int(await session.scalar(select(func.count()).select_from(Folder)) or 0) == 2
        assert int(await session.scalar(select(func.count()).select_from(SyncCycle)) or 0) == 1
        assert int(await session.scalar(select(func.count()).select_from(SyncCycleItem)) or 0) == 2
        cycle = await session.scalar(select(SyncCycle))
        assert cycle.anchor_at == anchor.replace(tzinfo=None) or cycle.anchor_at == anchor
        assert cycle.windows_completed == 0
    async with state_factory() as session:
        version = await session.get(SystemSetting, "sync_engine_version")
        completed = await session.get(SystemSetting, "initial_index_completed_at")
        assert version.value == "1.1"
        assert completed.value.startswith("2026-08-30T01:00:00")
    await state_engine.dispose()
    await index_engine.dispose()


async def test_empty_index_after_v11_is_recovery_not_first_install(monkeypatch):
    state_engine, index_engine, state_factory, _ = await _factories(monkeypatch)
    async with state_factory() as session:
        session.add_all(
            [
                SystemSetting(key="sync_engine_version", value="1.1"),
                SystemSetting(key="instance_initialized_at", value="2026-08-29T00:00:00+00:00"),
                SystemSetting(key="initial_index_completed_at", value="2026-08-29T01:00:00+00:00"),
                ContentRootMapping(id=1, content_type="software", display_name="软件", alist_path="/软件", enabled=True),
            ]
        )
        await session.commit()
    assert await rolling.resolve_rolling_mode() == "INDEX_RECOVERY_REQUIRED"
    cycle = await rolling.prepare_index_recovery(datetime(2026, 8, 30, tzinfo=timezone.utc))
    assert cycle is not None
    assert cycle.cycle_type == "recovery"
    assert await rolling.resolve_rolling_mode() == "NORMAL"
    async with state_factory() as session:
        completed = await session.get(SystemSetting, "initial_index_completed_at")
        assert completed.value == "2026-08-29T01:00:00+00:00"
    await state_engine.dispose()
    await index_engine.dispose()


async def test_rolling_window_scans_each_queued_folder_once_and_skips_fts_when_unchanged(monkeypatch):
    state_engine, index_engine, state_factory, index_factory = await _factories(monkeypatch)
    anchor = datetime(2026, 8, 30, tzinfo=timezone.utc)
    entries = rolling.validate_scope_entries(
        "/软件",
        [{"name": "A.zip", "is_dir": False, "size": 10, "modified": "2026-08-29T00:00:00Z"}],
    )
    fingerprint = rolling.scope_fingerprint(entries)
    async with state_factory() as session:
        session.add_all(
            [
                SystemSetting(key="sync_engine_version", value="1.1"),
                SystemSetting(key="instance_initialized_at", value="2026-08-28T00:00:00+00:00"),
                SystemSetting(key="initial_index_completed_at", value="2026-08-28T01:00:00+00:00"),
            ]
        )
        await session.commit()
    async with index_factory() as session:
        folder = Folder(id="f-root", name="软件", path="/软件", parent_id=None, content_type="software", root_mapping_id=1, status="active")
        cycle = SyncCycle(status="planned", cycle_type="normal", anchor_at=anchor, planned_folder_count=1)
        session.add_all([folder, cycle, FolderScanState(folder_id="f-root", path="/软件", fingerprint=fingerprint)])
        await session.flush()
        session.add(SyncCycleItem(cycle_id=cycle.id, folder_id="f-root", folder_path="/软件"))
        await session.commit()

    class FakeClient:
        calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def list_path(self, path: str, refresh: bool = False, strict: bool = False):
            assert path == "/软件"
            assert refresh is False
            assert strict is True
            self.calls += 1
            return [{"name": "A.zip", "is_dir": False, "size": 10, "modified": "2026-08-29T00:00:00Z"}]

    client = FakeClient()

    async def fake_load():
        return client, []

    async def circuit_closed():
        return {"open": False, "until": None, "reason": "", "failures": 0}

    monkeypatch.setattr(rolling, "load_client_and_roots", fake_load)
    monkeypatch.setattr(rolling, "sync_circuit_status", circuit_closed)
    result = await rolling.run_due_rolling_window(manual=True, now=anchor + timedelta(hours=6))
    assert result["status"] == "success"
    assert result["changed"] == 0
    assert result["unchanged"] == 1
    assert result["list_requests"] == 1
    assert client.calls == 1
    async with index_factory() as session:
        item = await session.scalar(select(SyncCycleItem))
        cycle = await session.scalar(select(SyncCycle))
        assert item.status == "success"
        assert cycle.status == "success"
        assert cycle.fts_rebuilt_count == 0
    await state_engine.dispose()
    await index_engine.dispose()


async def test_changed_scope_updates_direct_child_and_rebuilds_fts_once(monkeypatch):
    state_engine, index_engine, state_factory, index_factory = await _factories(monkeypatch)
    async with index_engine.begin() as connection:
        await connection.exec_driver_sql(
            "CREATE VIRTUAL TABLE search_fts USING fts5("
            "object_id UNINDEXED, object_type UNINDEXED, name, extension, "
            "content_type UNINDEXED, description, tags, breadcrumb_text)"
        )
    anchor = datetime(2026, 8, 30, tzinfo=timezone.utc)
    async with state_factory() as session:
        session.add_all(
            [
                SystemSetting(key="sync_engine_version", value="1.1"),
                SystemSetting(key="instance_initialized_at", value="2026-08-28T00:00:00+00:00"),
                SystemSetting(key="initial_index_completed_at", value="2026-08-28T01:00:00+00:00"),
            ]
        )
        await session.commit()
    async with index_factory() as session:
        folder = Folder(id="f-root", name="软件", path="/软件", parent_id=None, content_type="software", root_mapping_id=1, status="active")
        resource = Resource(id="r-a", name="A.zip", path="/软件/A.zip", parent_id="f-root", content_type="software", root_mapping_id=1, extension="zip", size=10, status="active")
        cycle = SyncCycle(status="planned", cycle_type="normal", anchor_at=anchor, planned_folder_count=1)
        session.add_all([folder, resource, cycle, FolderScanState(folder_id="f-root", path="/软件", fingerprint="old")])
        await session.flush()
        session.add(SyncCycleItem(cycle_id=cycle.id, folder_id="f-root", folder_path="/软件"))
        await session.commit()

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def list_path(self, path: str, refresh: bool = False, strict: bool = False):
            assert (path, refresh, strict) == ("/软件", False, True)
            return [{"name": "A.zip", "is_dir": False, "size": 20}]

    async def fake_load():
        return FakeClient(), []

    async def circuit_closed():
        return {"open": False, "until": None, "reason": "", "failures": 0}

    monkeypatch.setattr(rolling, "load_client_and_roots", fake_load)
    monkeypatch.setattr(rolling, "sync_circuit_status", circuit_closed)
    result = await rolling.run_due_rolling_window(manual=True, now=anchor + timedelta(hours=6))
    assert result["changed"] == 1
    async with index_factory() as session:
        resource = await session.get(Resource, "r-a")
        cycle = await session.scalar(select(SyncCycle))
        fts_count = int((await session.execute(text("SELECT COUNT(*) FROM search_fts"))).scalar_one())
        assert resource.size == 20
        assert cycle.fts_rebuilt_count == 1
        assert fts_count == 2
    await state_engine.dispose()
    await index_engine.dispose()
