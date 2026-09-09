"""Lifespan index-recovery boundary tests.

Prove that the real API startup (cloudsite.infrastructure.lifespan.lifespan)
treats a missing index.db as INDEX_RECOVERY, preserves state.db identity and
settings, and never falls back to first-time setup semantics.  A recovery
failure must not erase or rewrite state.db and must not start the scheduler or
startup sync.
"""
import asyncio
import sqlite3
from contextlib import suppress
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import database, indexer, main, search
from cloudsite.config import settings
from cloudsite.database import StateBase
from cloudsite.identity import migration as identity_migration
from cloudsite.models import (
    AListConnection,
    ContentRootMapping,
    SiteSettings,
    SystemSetting,
    User,
)
from cloudsite.sync import rolling

_INITIAL_INDEX_COMPLETED_AT = "2026-09-01T00:00:00+00:00"
_INSTANCE_INITIALIZED_AT = "2026-09-01T00:00:00+00:00"


async def _build_populated_state_db(state_path: Path) -> None:
    """Create a valid state.db with instance identity and rolling-engine markers."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{state_path}")
    async with engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(SiteSettings(id=1, site_name="RecoveryBoundary"))
        session.add(
            User(
                id=1,
                username="admin",
                username_normalized="admin",
                password_hash="x",
            )
        )
        session.add(AListConnection(id=1, base_url="http://alist.local", enabled=True))
        session.add(
            ContentRootMapping(
                id=1,
                content_type="software",
                display_name="Software",
                alist_path="/software",
                enabled=True,
                sort_order=0,
            )
        )
        session.add_all(
            [
                SystemSetting(key="setup_completed", value="true", value_type="string"),
                SystemSetting(
                    key="sync_engine_version",
                    value=rolling.SYNC_ENGINE_VERSION,
                    value_type="string",
                ),
                SystemSetting(
                    key="initial_index_completed_at",
                    value=_INITIAL_INDEX_COMPLETED_AT,
                    value_type="string",
                ),
                SystemSetting(
                    key="instance_initialized_at",
                    value=_INSTANCE_INITIALIZED_AT,
                    value_type="string",
                ),
                SystemSetting(key="schema_version", value="3", value_type="integer"),
                SystemSetting(key="sync_on_startup", value="true", value_type="boolean"),
            ]
        )
        await session.commit()
    await engine.dispose()


def _patch_database_targets(tmp_path: Path, monkeypatch) -> tuple:
    """Point every module-level engine/session factory at tmp_path databases."""
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    index_factory = async_sessionmaker(index_engine, expire_on_commit=False)

    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    monkeypatch.setattr(database, "StateSession", state_factory)
    monkeypatch.setattr(database, "IndexSession", index_factory)

    for module in (main, search, rolling, indexer, identity_migration):
        monkeypatch.setattr(module, "StateSession", state_factory)
        monkeypatch.setattr(module, "IndexSession", index_factory)

    return state_engine, index_engine, state_factory, index_factory


def _read_state_identity(state_path: Path) -> dict:
    """Read identity/settings rows from state.db for preservation checks."""
    conn = sqlite3.connect(str(state_path))
    try:
        users = conn.execute("SELECT id, username FROM users ORDER BY id").fetchall()
        alist = conn.execute(
            "SELECT id, base_url, enabled FROM alist_connections ORDER BY id"
        ).fetchall()
        site = conn.execute(
            "SELECT id, site_name FROM site_settings ORDER BY id"
        ).fetchall()
        keys = (
            "setup_completed",
            "sync_engine_version",
            "initial_index_completed_at",
            "instance_initialized_at",
        )
        sys_settings = {
            row[0]: row[1]
            for row in conn.execute(
                "SELECT key, value FROM system_settings WHERE key IN "
                f"({','.join('?' * len(keys))})",
                keys,
            ).fetchall()
        }
    finally:
        conn.close()
    return {
        "users": users,
        "alist_connections": alist,
        "site_settings": site,
        "system_settings": sys_settings,
    }


def _reset_task_handles() -> None:
    main.scheduler_task = None
    main.manual_sync_task = None


async def test_lifespan_index_loss_invokes_recovery_not_first_install(
    tmp_path, monkeypatch
):
    """A missing index.db with a populated state.db triggers INDEX_RECOVERY
    preparation, preserves state identity/settings, and starts the scheduler."""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    await _build_populated_state_db(tmp_path / "state.db")
    state_engine, index_engine, *_ = _patch_database_targets(tmp_path, monkeypatch)

    identity_before = _read_state_identity(tmp_path / "state.db")
    assert not (tmp_path / "index.db").exists()

    call_log: list[str] = []
    real_prepare = main.prepare_index_recovery

    async def tracked_prepare(*args, **kwargs):
        call_log.append("prepare_index_recovery")
        return await real_prepare(*args, **kwargs)

    monkeypatch.setattr(main, "prepare_index_recovery", tracked_prepare)

    async def fake_scheduler_loop():
        call_log.append("scheduler_started")
        await asyncio.sleep(3600)

    monkeypatch.setattr(main, "scheduler_loop", fake_scheduler_loop)

    async def fake_startup_sync():
        call_log.append("startup_sync")

    monkeypatch.setattr(main, "_safe_startup_sync", fake_startup_sync)

    _reset_task_handles()
    try:
        async with main.lifespan(main.app):
            assert main.scheduler_task is not None
            assert not main.scheduler_task.done()
            await asyncio.sleep(0.05)
        assert "prepare_index_recovery" in call_log
        assert "scheduler_started" in call_log
        assert "startup_sync" in call_log
    finally:
        _reset_task_handles()
        await state_engine.dispose()
        await index_engine.dispose()

    identity_after = _read_state_identity(tmp_path / "state.db")
    assert identity_after["users"] == identity_before["users"]
    assert identity_after["alist_connections"] == identity_before["alist_connections"]
    assert identity_after["site_settings"] == identity_before["site_settings"]
    assert identity_after["system_settings"] == identity_before["system_settings"]
    assert identity_after["system_settings"]["setup_completed"] == "true"
    assert (
        identity_after["system_settings"]["sync_engine_version"]
        == rolling.SYNC_ENGINE_VERSION
    )

    assert (tmp_path / "index.db").exists()
    conn = sqlite3.connect(str(tmp_path / "index.db"))
    try:
        folder_count = conn.execute(
            "SELECT COUNT(*) FROM folders WHERE status = 'active'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert folder_count >= 1


async def test_lifespan_index_recovery_failure_preserves_state_and_skips_scheduler(
    tmp_path, monkeypatch
):
    """When prepare_index_recovery raises, state.db identity/settings survive,
    and neither the scheduler nor startup sync is started."""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    await _build_populated_state_db(tmp_path / "state.db")
    state_engine, index_engine, *_ = _patch_database_targets(tmp_path, monkeypatch)

    identity_before = _read_state_identity(tmp_path / "state.db")

    call_log: list[str] = []

    async def failing_prepare(*args, **kwargs):
        call_log.append("prepare_index_recovery_failed")
        raise RuntimeError("simulated index recovery failure")

    monkeypatch.setattr(main, "prepare_index_recovery", failing_prepare)

    async def fake_scheduler_loop():
        call_log.append("scheduler_started")
        await asyncio.sleep(3600)

    monkeypatch.setattr(main, "scheduler_loop", fake_scheduler_loop)

    async def fake_startup_sync():
        call_log.append("startup_sync")

    monkeypatch.setattr(main, "_safe_startup_sync", fake_startup_sync)

    _reset_task_handles()
    try:
        with pytest.raises(RuntimeError, match="simulated index recovery failure"):
            async with main.lifespan(main.app):
                pass
    finally:
        if main.scheduler_task and not main.scheduler_task.done():
            main.scheduler_task.cancel()
            with suppress(asyncio.CancelledError):
                await main.scheduler_task
        _reset_task_handles()
        await state_engine.dispose()
        await index_engine.dispose()

    assert "prepare_index_recovery_failed" in call_log
    assert "scheduler_started" not in call_log
    assert "startup_sync" not in call_log
    assert main.scheduler_task is None

    assert (tmp_path / "state.db").exists()
    identity_after = _read_state_identity(tmp_path / "state.db")
    assert identity_after["users"] == identity_before["users"]
    assert identity_after["alist_connections"] == identity_before["alist_connections"]
    assert identity_after["site_settings"] == identity_before["site_settings"]
    for key in (
        "setup_completed",
        "sync_engine_version",
        "initial_index_completed_at",
        "instance_initialized_at",
    ):
        assert (
            identity_after["system_settings"][key]
            == identity_before["system_settings"][key]
        )
    assert identity_after["system_settings"]["setup_completed"] == "true"
