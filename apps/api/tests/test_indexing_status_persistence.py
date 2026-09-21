"""Indexing v2 progress persistence regression tests."""

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import database
from cloudsite.models import SystemSetting
from cloudsite.modules.indexing.infrastructure.legacy_bridge import (
    _log_operation,
    _update_v2_sync_status,
)
from cloudsite.modules.indexing.infrastructure.status_store import v2_sync_due
from cloudsite.platform.db import StateBase


async def test_v2_sync_status_persists_same_system_setting_payload(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)

    monkeypatch.setattr(database, "StateSession", factory)

    await _update_v2_sync_status(
        "running",
        2,
        5,
        17,
        "/docs/current",
        42,
        3,
        4,
        5,
        30,
    )

    async with factory() as session:
        row = await session.get(SystemSetting, "v2_sync_progress")
        assert row is not None
        payload = json.loads(row.value)
        assert payload == {
            "status": "running",
            "categories_done": 2,
            "categories_total": 5,
            "elapsed_seconds": 17,
            "current_path": "/docs/current",
            "entries_scanned": 42,
            "added": 3,
            "changed": 4,
            "removed": 5,
            "unchanged": 30,
        }
        assert row.value_type == "string"

    await engine.dispose()


async def test_v2_operation_log_uses_observability_boundary(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)

    monkeypatch.setattr(database, "StateSession", factory)

    await _log_operation(
        "sync",
        "v2_test",
        "x" * 2100,
        level="WARNING",
    )

    async with factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT level, module, action, message "
                    "FROM operation_logs ORDER BY id DESC LIMIT 1"
                )
            )
        ).one()
        assert row.level == "WARNING"
        assert row.module == "sync"
        assert row.action == "v2_test"
        assert row.message == "x" * 2000

    await engine.dispose()


async def test_v2_sync_due_uses_progress_updated_at_as_schedule_clock():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)

    now = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)

    async with factory() as state:
        assert await v2_sync_due(state, 180, now=now) is True

        state.add(
            SystemSetting(
                key="v2_sync_progress",
                value='{"status":"completed"}',
                value_type="string",
                updated_at=now - timedelta(minutes=179),
            )
        )
        await state.commit()

        assert await v2_sync_due(state, 180, now=now) is False

        row = await state.get(SystemSetting, "v2_sync_progress")
        assert row is not None
        row.updated_at = now - timedelta(minutes=180)
        await state.commit()
        assert await v2_sync_due(state, 180, now=now) is True

        row.value = '{"status":"running"}'
        row.updated_at = now - timedelta(hours=24)
        await state.commit()
        assert await v2_sync_due(state, 180, now=now) is False

    await engine.dispose()


async def test_concurrent_v2_progress_keeps_known_root_total_and_recent_path(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)

    monkeypatch.setattr(database, "StateSession", factory)

    await _update_v2_sync_status(
        "running",
        1,
        4,
        23,
        "",
        120,
        active_workers=8,
        directories_done=37,
        known_pending=12,
        entries_discovered=120,
        recent_paths=["/软件/开发", "/软件/开发/Python"],
    )

    async with factory() as session:
        row = await session.get(SystemSetting, "v2_sync_progress")
        assert row is not None
        payload = json.loads(row.value)

    assert payload["status"] == "running"
    assert payload["categories_done"] == 1
    assert payload["categories_total"] == 4
    assert payload["directories_done"] == 37
    assert payload["known_pending"] == 12
    assert payload["active_workers"] == 8
    assert payload["entries_discovered"] == 120
    assert payload["recent_paths"] == ["/软件/开发", "/软件/开发/Python"]
    assert payload["current_path"] == "/软件/开发/Python"

    await engine.dispose()
