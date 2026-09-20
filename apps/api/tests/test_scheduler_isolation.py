"""1.0 Scheduler 隔离测试。

验证一个 cleanup 任务异常不会导致整个 scheduler 永久死亡。
对应 1.0 开发文档第 46 节：Scheduler 隔离。

独立任务：Rolling / Session Cleanup / Download Cleanup / Share Cleanup / 其他 Maintenance
一个异常不能导致整个 Scheduler 永久死亡。
"""
import asyncio

import pytest

from cloudsite import main


async def test_run_cleanup_job_swallows_exception_and_logs(monkeypatch):
    """_run_cleanup_job 捕获异常并记录日志，不传播。"""
    logged = []

    async def fake_log(*args, **kwargs):
        logged.append((args, kwargs))

    monkeypatch.setattr(main, "log_operation", fake_log)

    async def failing_cleanup():
        raise RuntimeError("cleanup boom")

    # 不应抛出异常
    await main._run_cleanup_job("test_cleanup", "测试清理", failing_cleanup)

    # 应记录失败日志
    assert len(logged) >= 1
    assert any("failed" in str(args) or "失败" in str(args) for args, _ in logged)


async def test_run_cleanup_job_succeeds_and_logs(monkeypatch):
    """_run_cleanup_job 成功时记录完成日志。"""
    logged = []

    async def fake_log(*args, **kwargs):
        logged.append(args)

    monkeypatch.setattr(main, "log_operation", fake_log)

    async def good_cleanup():
        return 5

    await main._run_cleanup_job("test_cleanup", "测试清理", good_cleanup)

    assert len(logged) >= 1
    assert any("完成" in str(args) for args in logged)


async def test_run_cleanup_job_propagates_cancelled_error(monkeypatch):
    """_run_cleanup_job 正确传播 CancelledError（不吞掉取消信号）。"""
    async def fake_log(*args, **kwargs):
        pass

    monkeypatch.setattr(main, "log_operation", fake_log)

    async def cancelled_cleanup():
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await main._run_cleanup_job("test_cleanup", "测试清理", cancelled_cleanup)


async def test_scheduler_loop_survives_sync_failure(monkeypatch):
    """scheduler_loop 在 sync 失败后不永久死亡。"""
    call_count = 0

    async def fake_sleep(seconds):
        nonlocal call_count
        call_count += 1
        if call_count >= 3:
            raise asyncio.CancelledError()  # 停止循环

    monkeypatch.setattr(main.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(main, "_last_session_cleanup_at", 0.0)
    monkeypatch.setattr(main, "_last_rate_limit_cleanup_at", 0.0)
    monkeypatch.setattr(main, "_last_share_cleanup_at", 0.0)
    monkeypatch.setattr(main, "SESSION_CLEANUP_SECONDS", 0)
    monkeypatch.setattr(main, "DOWNLOAD_RATE_CLEANUP_SECONDS", 0)
    monkeypatch.setattr(main, "SHARE_CLEANUP_SECONDS", 0)

    async def failing_cleanup():
        raise RuntimeError("boom")

    monkeypatch.setattr(main, "cleanup_expired_user_sessions", failing_cleanup)
    monkeypatch.setattr(main, "cleanup_download_rate_limits", failing_cleanup)
    monkeypatch.setattr(main, "cleanup_terminal_shares", failing_cleanup)
    monkeypatch.setattr(main, "cleanup_share_verify_attempts", failing_cleanup)

    async def fake_log(*args, **kwargs):
        pass

    monkeypatch.setattr(main, "log_operation", fake_log)

    class FakeStateSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def scalars(self, *_):
            class FakeResult:
                def all(self):
                    return []
            return FakeResult()

    monkeypatch.setattr(main, "StateSession", FakeStateSession)

    # scheduler_loop 应在 3 次迭代后被 CancelledError 停止，而不是因为 cleanup 异常停止
    with pytest.raises(asyncio.CancelledError):
        await main.scheduler_loop()

    # 验证循环至少执行了 3 次（没有被 cleanup 异常中断）
    assert call_count >= 3
