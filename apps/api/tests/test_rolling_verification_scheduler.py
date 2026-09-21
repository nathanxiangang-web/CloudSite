"""R8 Scheduler wiring: full-sync priority, cadence, mutual exclusion, isolation."""

from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager

from cloudsite import main
from cloudsite.tasks import scheduler


class _Context(AbstractAsyncContextManager):
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _BusyTask:
    def done(self) -> bool:
        return False


def _wire_state(monkeypatch, *, automatic_sync: bool = True, interval: int = 360):
    state = object()
    monkeypatch.setattr(main, "StateSession", lambda: _Context(state))

    async def fake_values(got_state):
        assert got_state is state
        return {
            "automatic_sync": automatic_sync,
            "sync_interval_minutes": interval,
            "sync_on_startup": False,
        }

    monkeypatch.setattr(main, "get_system_values", fake_values)
    return state


async def test_full_sync_wins_when_both_actions_are_due(monkeypatch):
    state = _wire_state(monkeypatch)
    calls: list[str] = []

    async def full_due(got_state, interval):
        assert got_state is state
        assert interval == 360
        return True

    async def full_sync():
        assert main.manual_sync_task is asyncio.current_task()
        calls.append("full")
        return {"status": "success"}

    async def verification():
        raise AssertionError("verification must not run when full sync is due")

    monkeypatch.setattr(scheduler, "v2_sync_due", full_due)
    monkeypatch.setattr(scheduler, "run_indexing_v2_production", full_sync)
    monkeypatch.setattr(main, "_run_rolling_verification_job", verification)
    monkeypatch.setattr(scheduler.time, "monotonic", lambda: 12345.0)

    main.manual_sync_task = None
    main._last_rolling_verification_at = 0.0

    result = await scheduler._run_sync_or_verification_tick(5000.0)

    assert result == "full_sync"
    assert calls == ["full"]
    assert main.manual_sync_task is None
    assert main._last_rolling_verification_at == 12345.0


async def test_verification_runs_only_when_full_sync_not_due_and_interval_elapsed(monkeypatch):
    state = _wire_state(monkeypatch)
    calls: list[str] = []

    async def full_due(got_state, interval):
        assert got_state is state
        return False

    async def verification():
        assert main.manual_sync_task is asyncio.current_task()
        calls.append("verification")
        return {"status": "success", "roots": [], "errors": []}

    async def full_sync():
        raise AssertionError("full sync must not run")

    monkeypatch.setattr(scheduler, "v2_sync_due", full_due)
    monkeypatch.setattr(scheduler, "run_indexing_v2_production", full_sync)
    monkeypatch.setattr(main, "_run_rolling_verification_job", verification)

    main.manual_sync_task = None
    main._last_rolling_verification_at = 1000.0
    main.ROLLING_VERIFICATION_INTERVAL_SECONDS = 900

    result = await scheduler._run_sync_or_verification_tick(1900.0)

    assert result == "verification"
    assert calls == ["verification"]
    assert main.manual_sync_task is None
    assert main._last_rolling_verification_at == 1900.0


async def test_verification_stays_idle_before_interval(monkeypatch):
    _wire_state(monkeypatch)

    async def full_due(_state, _interval):
        return False

    async def verification():
        raise AssertionError("verification must respect low-frequency cadence")

    monkeypatch.setattr(scheduler, "v2_sync_due", full_due)
    monkeypatch.setattr(main, "_run_rolling_verification_job", verification)

    main.manual_sync_task = None
    main._last_rolling_verification_at = 1000.0
    main.ROLLING_VERIFICATION_INTERVAL_SECONDS = 900

    result = await scheduler._run_sync_or_verification_tick(1899.0)

    assert result == "idle"
    assert main._last_rolling_verification_at == 1000.0


async def test_existing_sync_task_blocks_both_scheduler_actions(monkeypatch):
    _wire_state(monkeypatch)

    async def full_due(_state, _interval):
        return True

    async def full_sync():
        raise AssertionError("busy scheduler must not start another full sync")

    async def verification():
        raise AssertionError("busy scheduler must not start verification")

    monkeypatch.setattr(scheduler, "v2_sync_due", full_due)
    monkeypatch.setattr(scheduler, "run_indexing_v2_production", full_sync)
    monkeypatch.setattr(main, "_run_rolling_verification_job", verification)

    main.manual_sync_task = _BusyTask()
    try:
        result = await scheduler._run_sync_or_verification_tick(9999.0)
    finally:
        main.manual_sync_task = None

    assert result == "busy"


async def test_automatic_sync_disabled_disables_verification_too(monkeypatch):
    _wire_state(monkeypatch, automatic_sync=False)

    async def fail_due(_state, _interval):
        raise AssertionError("disabled scheduler should not evaluate sync due")

    monkeypatch.setattr(scheduler, "v2_sync_due", fail_due)

    main.manual_sync_task = None
    main._last_rolling_verification_at = 0.0

    result = await scheduler._run_sync_or_verification_tick(9999.0)

    assert result == "disabled"


async def test_verification_exception_isolated_and_logged(monkeypatch):
    logged: list[tuple[tuple, dict]] = []

    async def boom(*, batch_size):
        assert batch_size == scheduler.ROLLING_VERIFICATION_BATCH_SIZE
        raise RuntimeError("provider verification boom")

    async def fake_log(*args, **kwargs):
        logged.append((args, kwargs))

    monkeypatch.setattr(scheduler, "run_rolling_verification_once", boom)
    monkeypatch.setattr(main, "log_operation", fake_log)

    result = await scheduler._run_rolling_verification_job()

    assert result["status"] == "failed"
    assert "provider verification boom" in result["errors"][0]
    assert any(
        args[1] == "rolling_verification_failed"
        and kwargs.get("level") == "ERROR"
        for args, kwargs in logged
    )


async def test_failed_verification_advances_cadence_to_avoid_retry_storm(monkeypatch):
    _wire_state(monkeypatch)
    calls = 0

    async def full_due(_state, _interval):
        return False

    async def failed_verification():
        nonlocal calls
        calls += 1
        return {"status": "failed", "roots": [], "errors": ["boom"]}

    monkeypatch.setattr(scheduler, "v2_sync_due", full_due)
    monkeypatch.setattr(main, "_run_rolling_verification_job", failed_verification)

    main.manual_sync_task = None
    main._last_rolling_verification_at = 0.0
    main.ROLLING_VERIFICATION_INTERVAL_SECONDS = 900

    first = await scheduler._run_sync_or_verification_tick(1000.0)
    second = await scheduler._run_sync_or_verification_tick(1060.0)

    assert first == "verification_failed"
    assert second == "idle"
    assert calls == 1
