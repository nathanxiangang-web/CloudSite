"""4 窗口分配 / manual 隔离 / 第四窗口 overdue 状态推进 / 并发占位。"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import search
from cloudsite.database import IndexBase, StateBase
from cloudsite.models import Folder, SyncCycle, SyncCycleItem, SystemSetting
from cloudsite.sync import rolling
from cloudsite.sync.path_sync import ManualSyncOrchestrator
from cloudsite.sync.planner import calculate_window_target


def test_459_items_distribute_across_4_windows_cover_all():
    targets = []
    remaining = 459
    for w in range(4):
        t = calculate_window_target(remaining, w, 4)
        targets.append(t)
        remaining -= t
    assert targets == [115, 115, 115, 114]
    assert remaining == 0


def test_new_subdir_enters_subsequent_window_recalculation():
    remaining_after_w0 = 459 - 115 + 10
    target_w1 = calculate_window_target(remaining_after_w0, 1, 4)
    assert target_w1 == -(-(remaining_after_w0) // 3)


def test_fourth_window_with_remaining_marks_overdue_eligible():
    # 第四窗口结束后仍有可重试项：windows_left 兜底为 1，可续跑
    assert calculate_window_target(1, 4, 4) == 1


async def _factories(monkeypatch):
    state_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    index_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    index_factory = async_sessionmaker(index_engine, expire_on_commit=False)
    async with state_engine.begin() as c:
        await c.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as c:
        await c.run_sync(IndexBase.metadata.create_all)
    monkeypatch.setattr(rolling, "StateSession", state_factory)
    monkeypatch.setattr(rolling, "IndexSession", index_factory)
    monkeypatch.setattr(search, "StateSession", state_factory)
    monkeypatch.setattr(search, "IndexSession", index_factory)

    async def no_log(*_, **__):
        return None

    monkeypatch.setattr(rolling, "log_operation", no_log)
    return state_engine, index_engine, state_factory, index_factory


async def test_manual_path_cycle_excluded_from_rolling_active_cycle(monkeypatch):
    """数据库中同时存在 manual/normal active cycle 时，_active_cycle 返回 normal。"""
    state_engine, index_engine, state_factory, index_factory = await _factories(monkeypatch)
    anchor = datetime(2026, 9, 6, tzinfo=timezone.utc)
    async with index_factory() as session:
        normal = SyncCycle(cycle_type="normal", status="planned", anchor_at=anchor, planned_folder_count=1)
        manual = SyncCycle(cycle_type="manual_path", status="running", anchor_at=anchor, planned_folder_count=1)
        session.add_all([normal, manual])
        await session.flush()
        session.add(SyncCycleItem(cycle_id=normal.id, folder_id="f1", folder_path="/a"))
        session.add(SyncCycleItem(cycle_id=manual.id, folder_id="f2", folder_path="/b"))
        await session.commit()
        active = await rolling._active_cycle(session)
        assert active is not None
        assert active.id == normal.id
        assert active.cycle_type == "normal"
    await state_engine.dispose()
    await index_engine.dispose()


async def test_fourth_window_completion_with_remaining_marks_cycle_overdue(monkeypatch):
    """4 窗口全部完成后仍有可重试 item，cycle.status 推进为 overdue。"""
    state_engine, index_engine, state_factory, index_factory = await _factories(monkeypatch)
    anchor = datetime(2026, 8, 30, tzinfo=timezone.utc)
    async with state_factory() as session:
        session.add_all([
            SystemSetting(key="sync_engine_version", value="1.1"),
            SystemSetting(key="instance_initialized_at", value="2026-08-28T00:00:00+00:00"),
            SystemSetting(key="initial_index_completed_at", value="2026-08-28T01:00:00+00:00"),
        ])
        await session.commit()
    async with index_factory() as session:
        folder = Folder(id="f-root", name="软件", path="/软件", parent_id=None, content_type="software", root_mapping_id=1, status="active")
        cycle = SyncCycle(status="running", cycle_type="normal", anchor_at=anchor, planned_folder_count=1, windows_completed=4)
        session.add_all([folder, cycle])
        await session.flush()
        session.add(SyncCycleItem(cycle_id=cycle.id, folder_id="f-root", folder_path="/软件", status="failed", attempts=1))
        await session.commit()

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def list_path(self, path, refresh=False, strict=False):
            raise RuntimeError("scan failed")

    async def fake_load():
        return FakeClient(), []

    async def circuit_closed():
        return {"open": False, "until": None, "reason": "", "failures": 0}

    monkeypatch.setattr(rolling, "load_client_and_roots", fake_load)
    monkeypatch.setattr(rolling, "sync_circuit_status", circuit_closed)
    now = anchor + timedelta(hours=24, minutes=1)
    result = await rolling.run_due_rolling_window(manual=True, now=now)
    async with index_factory() as session:
        cycle = await session.scalar(select(SyncCycle).where(SyncCycle.cycle_type == "normal"))
        assert cycle.status == "overdue"
    await state_engine.dispose()
    await index_engine.dispose()


def test_concurrent_manual_reserve_only_one_accepted():
    orch = ManualSyncOrchestrator.instance()
    orch._running = False
    first = orch.try_reserve()
    second = orch.try_reserve()
    assert first is True
    assert second is False
    orch.release()
    assert orch.can_start() is True


def test_release_allows_next_reserve():
    orch = ManualSyncOrchestrator.instance()
    orch._running = False
    assert orch.try_reserve() is True
    orch.release()
    assert orch.try_reserve() is True
    orch.release()
