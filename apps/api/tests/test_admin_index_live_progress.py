"""Admin indexing live-progress contract regressions."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import main, models  # noqa: F401 - register metadata
from cloudsite.modules.indexing.infrastructure.status_store import (
    write_v2_sync_progress,
)
from cloudsite.platform.db import IndexBase, StateBase
from cloudsite.routers.admin.index import admin_index_summary
from cloudsite.routers.admin.sync import admin_sync_status


class _BusyTask:
    def done(self) -> bool:
        return False


async def _stores():
    index_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    state_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    index_factory = async_sessionmaker(index_engine, expire_on_commit=False)
    state_factory = async_sessionmaker(state_engine, expire_on_commit=False)

    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)
    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)

    return index_engine, state_engine, index_factory, state_factory


async def test_admin_sync_status_exposes_truthful_live_root_and_directory_metrics(
    monkeypatch,
):
    index_engine, state_engine, index_factory, state_factory = await _stores()
    monkeypatch.setattr(main, "IndexSession", index_factory)
    monkeypatch.setattr(main, "StateSession", state_factory)
    main.manual_sync_task = None

    try:
        async with state_factory() as state:
            await write_v2_sync_progress(
                state,
                status="running",
                categories_done=1,
                categories_total=4,
                elapsed_seconds=27,
                active_workers=8,
                directories_done=37,
                known_pending=12,
                entries_discovered=120,
                recent_paths=["/软件/开发", "/软件/开发/Python"],
            )
            await state.commit()

        payload = await admin_sync_status()

        assert payload["status"] == "running"
        assert payload["roots_completed"] == 1
        assert payload["roots_total"] == 4
        assert payload["directories_done"] == 37
        assert payload["known_pending"] == 12
        assert payload["active_workers"] == 8
        assert payload["entries_discovered"] == 120
        assert payload["current_path"] == "/软件/开发/Python"
        assert payload["recent_paths"][-1] == "/软件/开发/Python"
    finally:
        main.manual_sync_task = None
        await index_engine.dispose()
        await state_engine.dispose()


async def test_admin_index_summary_does_not_treat_verification_lock_as_full_sync(
    monkeypatch,
):
    index_engine, state_engine, index_factory, state_factory = await _stores()
    monkeypatch.setattr(main, "IndexSession", index_factory)
    monkeypatch.setattr(main, "StateSession", state_factory)

    try:
        async with state_factory() as state:
            await write_v2_sync_progress(
                state,
                status="completed",
                categories_done=4,
                categories_total=4,
                elapsed_seconds=31,
                active_workers=0,
                directories_done=99,
                known_pending=0,
                entries_discovered=540,
                recent_paths=["/教程/最后目录"],
                added=2,
                changed=1,
                unchanged=537,
            )
            await state.commit()

        # Scheduler rolling verification reuses this handle as a mutex. It is
        # not evidence that a full sync is running.
        main.manual_sync_task = _BusyTask()

        payload = await admin_index_summary()

        assert payload["syncing"] is False
        latest = payload["latest_sync"]
        assert latest is not None
        assert latest["status"] == "completed"
        assert latest["roots_completed"] == 4
        assert latest["roots_total"] == 4
        assert latest["folders_scanned"] == 99
        assert latest["resources_scanned"] == 540
        assert latest["current_path"] == "/教程/最后目录"
        assert latest["directories_done"] == 99
        assert latest["entries_discovered"] == 540
    finally:
        main.manual_sync_task = None
        await index_engine.dispose()
        await state_engine.dispose()
