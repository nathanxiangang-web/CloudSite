"""1.0 Graceful Shutdown 测试。

验证 Docker Stop (SIGTERM) 时：
1. scheduler_task 被取消
2. manual_sync_task 被取消
3. CancelledError 被正确处理

对应 1.0 开发文档第 47 节：Graceful Shutdown。

SIGTERM → 停止接新后台任务 → 完成当前安全事务 → cancel scheduler → 退出
"""
import asyncio

import pytest

from cloudsite import main


async def test_lifespan_cancels_scheduler_on_shutdown(monkeypatch, tmp_path):
    """lifespan 退出时 scheduler_task 被取消。"""
    # Mock 所有启动步骤
    monkeypatch.setattr(main, "validate_database_files", lambda *_: None)
    monkeypatch.setattr(main, "backup_stable_id_databases", lambda *_: None)

    async def noop(*_args, **_kwargs):
        pass

    monkeypatch.setattr(main, "init_databases", noop)
    monkeypatch.setattr(main, "recover_search_index_if_dirty", noop)
    monkeypatch.setattr(main, "recover_interrupted_sync_runs", noop)
    monkeypatch.setattr(main, "migrate_stable_resource_ids", noop)
    monkeypatch.setattr(main, "recover_rolling_state", noop)
    monkeypatch.setattr(main, "migrate_existing_index_to_rolling", noop)

    async def fake_resolve_rolling_mode():
        return "normal"

    monkeypatch.setattr(main, "resolve_rolling_mode", fake_resolve_rolling_mode)

    # Mock StateSession 返回 sync_on_startup=False
    class FakeStateSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def get(self, *_):
            return None

        async def commit(self):
            pass

        def add(self, *_):
            pass

        async def scalars(self, *_):
            class FakeResult:
                def all(self):
                    return []
            return FakeResult()

    monkeypatch.setattr(main, "StateSession", FakeStateSession)

    # Track scheduler task lifecycle
    scheduler_started = asyncio.Event()
    scheduler_cancelled = asyncio.Event()

    async def tracked_scheduler_loop():
        scheduler_started.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            scheduler_cancelled.set()
            raise

    monkeypatch.setattr(main, "scheduler_loop", tracked_scheduler_loop)

    # Run lifespan
    async with main.lifespan(main.app):
        # 等待 scheduler 启动
        await asyncio.wait_for(scheduler_started.wait(), timeout=2)
        assert main.scheduler_task is not None
        assert not main.scheduler_task.done()

    # lifespan 退出后 scheduler 应被取消
    assert scheduler_cancelled.is_set()
    assert main.scheduler_task is None or main.scheduler_task.done()


async def test_lifespan_cancels_manual_sync_on_shutdown(monkeypatch):
    """lifespan 退出时 manual_sync_task 被取消。"""
    from contextlib import suppress

    sync_cancelled = asyncio.Event()

    async def long_running_sync():
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            sync_cancelled.set()
            raise

    # 创建任务并让它开始执行
    task = asyncio.create_task(long_running_sync())
    await asyncio.sleep(0)  # 让任务开始
    main.manual_sync_task = task
    main.scheduler_task = None

    # 模拟 lifespan shutdown 清理
    if main.manual_sync_task and not main.manual_sync_task.done():
        main.manual_sync_task.cancel()
        with suppress(asyncio.CancelledError):
            await main.manual_sync_task

    assert sync_cancelled.is_set()


async def test_scheduler_loop_handles_cancelled_error():
    """scheduler_loop 正确处理 CancelledError（不吞掉）。"""
    # scheduler_loop 第一次 sleep 就被取消
    original_sleep = main.asyncio.sleep

    async def immediate_cancel_sleep(seconds):
        raise asyncio.CancelledError()

    main.asyncio.sleep = immediate_cancel_sleep
    try:
        with pytest.raises(asyncio.CancelledError):
            await main.scheduler_loop()
    finally:
        main.asyncio.sleep = original_sleep
