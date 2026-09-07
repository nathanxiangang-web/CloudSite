"""Manual path-sync 集成测试：1 父目录=1 次 list_path、不递归、异常收尾、唯一约束。"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import search
from cloudsite.database import IndexBase, StateBase
from cloudsite.models import (
    ContentRootMapping,
    Folder,
    SyncCycle,
    SyncCycleItem,
    SyncRun,
    SystemSetting,
)
from cloudsite.sync import rolling
from cloudsite.sync import path_sync


async def _factories(monkeypatch):
    state_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    index_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    index_factory = async_sessionmaker(index_engine, expire_on_commit=False)
    async with state_engine.begin() as c:
        await c.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as c:
        await c.run_sync(IndexBase.metadata.create_all)
        await c.exec_driver_sql(
            "CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5("
            "object_id UNINDEXED, object_type UNINDEXED, name, extension, "
            "content_type UNINDEXED, description, tags, breadcrumb_text, "
            "tokenize='unicode61 remove_diacritics 2')"
        )
    monkeypatch.setattr(rolling, "StateSession", state_factory)
    monkeypatch.setattr(rolling, "IndexSession", index_factory)
    monkeypatch.setattr(path_sync, "StateSession", state_factory)
    monkeypatch.setattr(path_sync, "IndexSession", index_factory)
    monkeypatch.setattr(search, "StateSession", state_factory)
    monkeypatch.setattr(search, "IndexSession", index_factory)

    async def no_log(*_, **__):
        return None

    monkeypatch.setattr(rolling, "log_operation", no_log)
    return state_engine, index_engine, state_factory, index_factory


async def _seed_rolling(monkeypatch):
    """Seed state.db + a rolling cycle with /软件 so manual can target the same folder."""
    state_engine, index_engine, state_factory, index_factory = await _factories(monkeypatch)
    anchor = datetime(2026, 9, 6, tzinfo=timezone.utc)
    async with state_factory() as session:
        session.add_all([
            SystemSetting(key="sync_engine_version", value="1.1"),
            SystemSetting(key="instance_initialized_at", value="2026-09-01T00:00:00+00:00"),
            SystemSetting(key="initial_index_completed_at", value="2026-09-01T01:00:00+00:00"),
        ])
        await session.commit()
    async with index_factory() as session:
        folder = Folder(id="f-root", name="软件", path="/软件", parent_id=None, content_type="software", root_mapping_id=1, status="active")
        cycle = SyncCycle(cycle_type="normal", status="planned", anchor_at=anchor, planned_folder_count=1)
        session.add_all([folder, cycle])
        await session.flush()
        session.add(SyncCycleItem(cycle_id=cycle.id, folder_id="f-root", folder_path="/软件"))
        await session.commit()
    return state_engine, index_engine, state_factory, index_factory


class _FakeClient:
    def __init__(self, entries, refresh_seen=None):
        self.entries = entries
        self.refresh_seen = refresh_seen
        self.calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def list_path(self, path, refresh=False, strict=False):
        self.calls += 1
        if self.refresh_seen is not None:
            self.refresh_seen.append(refresh)
        return self.entries


async def test_manual_cycle_does_not_collide_with_rolling_cycle_unique_constraint(monkeypatch):
    """同一 folder 同时存在于 active Rolling cycle 和 manual cycle，不撞唯一约束。"""
    state_engine, index_engine, state_factory, index_factory = await _seed_rolling(monkeypatch)
    client = _FakeClient([])
    async def fake_load():
        return client, []
    monkeypatch.setattr(rolling, "load_client_and_roots", fake_load)
    monkeypatch.setattr(path_sync, "load_client_and_roots", fake_load)
    result = await path_sync.run_path_sync(["/软件"], set(), now=datetime(2026, 9, 6, 1, tzinfo=timezone.utc))
    assert result["status"] == "success"
    async with index_factory() as session:
        cycles = list((await session.scalars(select(SyncCycle).order_by(SyncCycle.id))).all())
        assert len(cycles) == 2
        items = list((await session.scalars(select(SyncCycleItem))).all())
        assert len(items) == 2
    await state_engine.dispose()
    await index_engine.dispose()


async def test_manual_scan_does_not_enqueue_descendant_items(monkeypatch):
    """manual 扫描后 manual cycle 没有后代 pending item（enqueue_discovered=False）。"""
    state_engine, index_engine, state_factory, index_factory = await _seed_rolling(monkeypatch)
    entries = [{"name": "sub", "is_dir": True, "size": 0, "modified": "2026-09-05T00:00:00Z"}]
    client = _FakeClient(entries)
    async def fake_load():
        return client, []
    monkeypatch.setattr(rolling, "load_client_and_roots", fake_load)
    monkeypatch.setattr(path_sync, "load_client_and_roots", fake_load)
    result = await path_sync.run_path_sync(["/软件"], set(), now=datetime(2026, 9, 6, 1, tzinfo=timezone.utc))
    assert result["status"] == "success"
    async with index_factory() as session:
        manual_cycle = await session.scalar(select(SyncCycle).where(SyncCycle.cycle_type == "manual_path"))
        items = list((await session.scalars(select(SyncCycleItem).where(SyncCycleItem.cycle_id == manual_cycle.id))).all())
        assert len(items) == 1
        assert items[0].folder_path == "/软件"
    await state_engine.dispose()
    await index_engine.dispose()


async def test_client_init_failure_finalizes_run_cycle_not_running(monkeypatch):
    """客户端初始化失败后 run/cycle 非 running。"""
    state_engine, index_engine, state_factory, index_factory = await _seed_rolling(monkeypatch)
    async def fake_load():
        raise RuntimeError("client init failed")
    monkeypatch.setattr(rolling, "load_client_and_roots", fake_load)
    monkeypatch.setattr(path_sync, "load_client_and_roots", fake_load)
    result = await path_sync.run_path_sync(["/软件"], set(), now=datetime(2026, 9, 6, 1, tzinfo=timezone.utc))
    assert result["status"] == "failed"
    async with index_factory() as session:
        run = await session.scalar(select(SyncRun).where(SyncRun.sync_type == "manual_path"))
        assert run.status != "running"
        cycle = await session.scalar(select(SyncCycle).where(SyncCycle.cycle_type == "manual_path"))
        assert cycle.status != "running"
    await state_engine.dispose()
    await index_engine.dispose()


async def test_manual_one_path_one_list_request(monkeypatch):
    """1 个合法路径 = 1 次 list_path，list_requests=1。"""
    state_engine, index_engine, state_factory, index_factory = await _seed_rolling(monkeypatch)
    client = _FakeClient([])
    async def fake_load():
        return client, []
    monkeypatch.setattr(rolling, "load_client_and_roots", fake_load)
    monkeypatch.setattr(path_sync, "load_client_and_roots", fake_load)
    result = await path_sync.run_path_sync(["/软件"], set(), now=datetime(2026, 9, 6, 1, tzinfo=timezone.utc))
    assert result["list_requests"] == 1
    assert client.calls == 1
    await state_engine.dispose()
    await index_engine.dispose()


async def test_manual_refresh_passed_to_client(monkeypatch):
    """force_refresh=True 时 client.list_path 收到 refresh=True。"""
    state_engine, index_engine, state_factory, index_factory = await _seed_rolling(monkeypatch)
    refresh_seen = []
    client = _FakeClient([], refresh_seen)
    async def fake_load():
        return client, []
    monkeypatch.setattr(rolling, "load_client_and_roots", fake_load)
    monkeypatch.setattr(path_sync, "load_client_and_roots", fake_load)
    await path_sync.run_path_sync(["/软件"], {"/软件"}, now=datetime(2026, 9, 6, 1, tzinfo=timezone.utc))
    assert refresh_seen == [True]
    await state_engine.dispose()
    await index_engine.dispose()


async def test_manual_partial_when_some_paths_not_found(monkeypatch):
    """部分路径找不到时 run 为 partial，failed/roots_failed 包含 path error 数量。"""
    state_engine, index_engine, state_factory, index_factory = await _seed_rolling(monkeypatch)
    client = _FakeClient([])
    async def fake_load():
        return client, []
    monkeypatch.setattr(rolling, "load_client_and_roots", fake_load)
    monkeypatch.setattr(path_sync, "load_client_and_roots", fake_load)
    result = await path_sync.run_path_sync(["/软件", "/不存在"], set(), now=datetime(2026, 9, 6, 1, tzinfo=timezone.utc))
    assert result["status"] == "partial"
    assert result["failed"] == 1
    assert len(result["path_errors"]) == 1
    async with index_factory() as session:
        run = await session.scalar(select(SyncRun).where(SyncRun.sync_type == "manual_path"))
        assert run.roots_failed == 1
        cycle = await session.scalar(select(SyncCycle).where(SyncCycle.cycle_type == "manual_path"))
        assert cycle.status == "partial"
    await state_engine.dispose()
    await index_engine.dispose()


async def test_manual_all_paths_not_found_is_failed(monkeypatch):
    state_engine, index_engine, state_factory, index_factory = await _factories(monkeypatch)
    async with index_factory() as session:
        session.add(Folder(id="f-x", name="x", path="/x", parent_id=None, content_type="software", root_mapping_id=1, status="active"))
        await session.commit()
    client = _FakeClient([])
    async def fake_load():
        return client, []
    monkeypatch.setattr(rolling, "load_client_and_roots", fake_load)
    monkeypatch.setattr(path_sync, "load_client_and_roots", fake_load)
    result = await path_sync.run_path_sync(["/不存在"], set(), now=datetime(2026, 9, 6, 1, tzinfo=timezone.utc))
    assert result["status"] == "failed"
    assert result["failed"] == 1
    await state_engine.dispose()
    await index_engine.dispose()
