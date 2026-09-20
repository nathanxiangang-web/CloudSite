"""R0 PR 04: cancel and state unification regression tests.

Cancel must update v2_sync_progress to "cancelled". Scheduler and startup
sync must set manual_sync_task so cancel and status endpoints work correctly.
Startup sync failures must be logged, not silently suppressed.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.models import SystemSetting
from cloudsite.modules.indexing.infrastructure.status_store import (
    read_v2_sync_progress,
    write_v2_sync_progress,
)
from cloudsite.platform.db import StateBase


async def _make_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)
    return engine, factory


async def test_write_v2_sync_progress_upserts():
    """write_v2_sync_progress should insert or update the progress row."""
    engine, factory = await _make_factory()
    try:
        async with factory() as session:
            await write_v2_sync_progress(session, status="running", categories_done=1)
            await session.commit()

        async with factory() as session:
            progress = await read_v2_sync_progress(session)
            assert progress["status"] == "running"
            assert progress["categories_done"] == 1

        async with factory() as session:
            await write_v2_sync_progress(session, status="cancelled")
            await session.commit()

        async with factory() as session:
            progress = await read_v2_sync_progress(session)
            assert progress["status"] == "cancelled"
            assert progress["categories_done"] == 0
    finally:
        await engine.dispose()


async def test_cancel_updates_v2_sync_progress():
    """Cancel endpoint must set v2_sync_progress to 'cancelled'."""
    from cloudsite.routers.admin.sync import cancel_sync

    engine, factory = await _make_factory()
    try:
        async with factory() as session:
            await write_v2_sync_progress(session, status="running")
            await session.commit()

        fake_task = MagicMock()
        fake_task.done.return_value = False
        fake_task.cancel = MagicMock()

        with patch("cloudsite.main.manual_sync_task", fake_task), \
             patch("cloudsite.main.StateSession", factory):
            result = await cancel_sync()

        assert result["status"] == "cancelled"
        fake_task.cancel.assert_called_once()

        async with factory() as session:
            progress = await read_v2_sync_progress(session)
            assert progress["status"] == "cancelled"
    finally:
        await engine.dispose()


async def test_cancel_not_running():
    """Cancel when no task is running should return not_running."""
    from cloudsite.routers.admin.sync import cancel_sync

    fake_main = MagicMock()
    fake_main.manual_sync_task = None

    with patch("cloudsite.main", fake_main):
        result = await cancel_sync()

    assert result["status"] == "not_running"


async def test_startup_sync_sets_manual_sync_task(monkeypatch):
    """_safe_startup_sync must set manual_sync_task so cancel works."""
    from cloudsite.tasks import sync as sync_module

    sync_called = False

    async def fake_run_production():
        nonlocal sync_called
        sync_called = True

    async def fake_log(*args, **kwargs):
        pass

    fake_main = MagicMock()
    fake_main.StateSession = MagicMock()
    fake_main.get_system_values = AsyncMock(
        return_value={"sync_on_startup": True, "sync_interval_minutes": 360}
    )
    fake_main.manual_sync_task = None
    fake_main.log_operation = fake_log

    fake_session = AsyncMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)
    fake_main.StateSession = MagicMock(return_value=fake_session)

    monkeypatch.setattr(sync_module, "run_indexing_v2_production", fake_run_production)
    monkeypatch.setattr(sync_module, "v2_sync_due", AsyncMock(return_value=True))
    monkeypatch.setattr(sync_module, "settings", MagicMock(
        sync_startup_delay_min_seconds=0,
        sync_startup_delay_max_seconds=0,
    ))
    monkeypatch.setattr("cloudsite.main", fake_main)

    await sync_module._safe_startup_sync()

    assert sync_called is True
    assert fake_main.manual_sync_task is None


async def test_startup_sync_logs_error(monkeypatch):
    """Startup sync failures must be logged, not silently suppressed."""
    from cloudsite.tasks import sync as sync_module

    log_calls: list[tuple] = []

    async def fake_run_production():
        raise RuntimeError("startup boom")

    async def fake_log(module, action, message, level="INFO"):
        log_calls.append((module, action, message, level))

    fake_main = MagicMock()
    fake_main.get_system_values = AsyncMock(
        return_value={"sync_on_startup": True, "sync_interval_minutes": 360}
    )
    fake_main.manual_sync_task = None
    fake_main.log_operation = fake_log

    fake_session = AsyncMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)
    fake_main.StateSession = MagicMock(return_value=fake_session)

    monkeypatch.setattr(sync_module, "run_indexing_v2_production", fake_run_production)
    monkeypatch.setattr(sync_module, "v2_sync_due", AsyncMock(return_value=True))
    monkeypatch.setattr(sync_module, "settings", MagicMock(
        sync_startup_delay_min_seconds=0,
        sync_startup_delay_max_seconds=0,
    ))
    monkeypatch.setattr("cloudsite.main", fake_main)

    await sync_module._safe_startup_sync()

    assert len(log_calls) == 1
    assert log_calls[0][0] == "sync"
    assert log_calls[0][1] == "startup_sync_failed"
    assert "startup boom" in log_calls[0][2]
    assert log_calls[0][3] == "ERROR"
    assert fake_main.manual_sync_task is None