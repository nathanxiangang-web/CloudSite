"""Lifespan startup boundary tests for state.db fail-closed behavior.

These tests enter the real FastAPI lifespan (cloudsite.infrastructure.lifespan.lifespan)
to prove DatabaseRecoveryRequired is raised at the recovery preflight, before database
initialization, setup mutation, scheduler creation, or sync startup.

Tripwires are installed after the recovery preflight: if startup proceeds past the
preflight, the first reached tripwire raises AssertionError with the step name.
"""

import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI

from cloudsite.config import settings
from cloudsite.database import (
    DatabaseRecoveryRequired,
    INDEX_REQUIRED_TABLES,
)
from cloudsite.infrastructure.lifespan import lifespan


def _create_database(path: Path, tables: set[str]) -> None:
    connection = sqlite3.connect(path)
    try:
        for table in sorted(tables):
            connection.execute(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY)')
        connection.commit()
    finally:
        connection.close()


def _install_startup_tripwires(monkeypatch) -> list[str]:
    """Replace every post-preflight step in main with a tripwire.

    Returns a list recording which steps were reached. If the recovery preflight
    raises DatabaseRecoveryRequired, the list stays empty.
    """
    from cloudsite import main

    reached: list[str] = []

    def _sync_tripwire(name: str):
        def _fn(*args, **kwargs):
            reached.append(name)
            raise AssertionError(f"startup proceeded past preflight to: {name}")

        return _fn

    def _async_tripwire(name: str):
        async def _fn(*args, **kwargs):
            reached.append(name)
            raise AssertionError(f"startup proceeded past preflight to: {name}")

        return _fn

    class _TripwireSession:
        async def __aenter__(self):
            reached.append("StateSession")
            raise AssertionError(
                "startup proceeded past preflight to: StateSession (setup mutation)"
            )

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(
        main, "backup_stable_id_databases", _sync_tripwire("backup_stable_id_databases")
    )
    monkeypatch.setattr(main, "init_databases", _async_tripwire("init_databases"))
    monkeypatch.setattr(
        main,
        "recover_search_index_if_dirty",
        _async_tripwire("recover_search_index_if_dirty"),
    )
    monkeypatch.setattr(
        main,
        "recover_interrupted_sync_runs",
        _async_tripwire("recover_interrupted_sync_runs"),
    )
    monkeypatch.setattr(
        main,
        "migrate_stable_resource_ids",
        _async_tripwire("migrate_stable_resource_ids"),
    )

    monkeypatch.setattr(main, "StateSession", lambda *a, **kw: _TripwireSession())
    monkeypatch.setattr(main, "scheduler_loop", _async_tripwire("scheduler_loop"))
    monkeypatch.setattr(
        main, "_safe_startup_sync", _async_tripwire("_safe_startup_sync")
    )

    return reached


async def test_lifespan_raises_when_state_db_missing_with_existing_index(
    tmp_path, monkeypatch
):
    """Existing index.db + missing state.db => lifespan raises at preflight."""
    _create_database(tmp_path / "index.db", INDEX_REQUIRED_TABLES)
    assert not (tmp_path / "state.db").exists()

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    reached = _install_startup_tripwires(monkeypatch)

    with pytest.raises(DatabaseRecoveryRequired) as error:
        async with lifespan(FastAPI()):
            pass

    assert error.value.code == "STATE_RECOVERY_REQUIRED"
    assert reached == []
    assert not (tmp_path / "state.db").exists()


async def test_lifespan_raises_when_state_db_corrupt_with_existing_index(
    tmp_path, monkeypatch
):
    """Existing index.db + corrupt state.db => lifespan raises at preflight."""
    _create_database(tmp_path / "index.db", INDEX_REQUIRED_TABLES)
    corrupt_bytes = b"corrupt state db -- not sqlite"
    (tmp_path / "state.db").write_bytes(corrupt_bytes)

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    reached = _install_startup_tripwires(monkeypatch)

    with pytest.raises(DatabaseRecoveryRequired) as error:
        async with lifespan(FastAPI()):
            pass

    assert error.value.code == "STATE_RECOVERY_REQUIRED"
    assert reached == []
    assert (tmp_path / "state.db").read_bytes() == corrupt_bytes


async def test_tripwire_fires_when_preflight_passes(tmp_path, monkeypatch):
    """Sanity check: with a fresh data dir, the preflight passes and the
    first tripwire fires, proving the tripwires are correctly installed."""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    reached = _install_startup_tripwires(monkeypatch)

    with pytest.raises(AssertionError, match="backup_stable_id_databases"):
        async with lifespan(FastAPI()):
            pass

    assert reached == ["backup_stable_id_databases"]
