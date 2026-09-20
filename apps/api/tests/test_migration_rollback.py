"""R1 supplement: migration downgrade/rollback path tests (V2 doc section 76).

V2 doc section 76 requires that the migration downgrade/rollback path be
exercised. The production chain is forward-only (state_v30_to_v31_upgrade
creates the durable scan tables); the downgrade plan constructed below is the
explicit reverse of that upgrade, executed in tests only so the rollback
contract is documented and verified.

Exercises:
- test_v31_downgrade_plan_exists: a v31 -> v30 downgrade plan is well-formed
  (correct from/to versions, callable upgrade, drops durable scan tables)
- test_downgrade_preserves_data: downgrade drops only durable scan tables;
  production data (site_settings, content_root_mappings) survives
- test_downgrade_drops_durable_scan_tables: downgrade removes
  index_scan_runs, index_scan_dirs, index_scan_entries
- test_reupgrade_after_downgrade: after downgrade to v30, re-running
  init_databases re-upgrades to CURRENT_SCHEMA_VERSION and recreates the
  durable scan tables
- test_migration_idempotent: running init_databases twice does not raise and
  schema_version remains at CURRENT_SCHEMA_VERSION

All databases are temporary under tmp_path; no production paths are touched.
"""
from __future__ import annotations

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import database
from cloudsite.database import StateBase
from cloudsite.migrations import (
    CURRENT_SCHEMA_VERSION,
    Migration,
    get_state_schema_version,
    set_state_schema_version,
)
from cloudsite.modules.site.infrastructure.models import SiteSettings


DURABLE_TABLES = ("index_scan_runs", "index_scan_dirs", "index_scan_entries")


def _enable_foreign_keys(engine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn, _record):  # noqa: ANN001
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


async def _init_engines(tmp_path, monkeypatch):
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    _enable_foreign_keys(state_engine)
    _enable_foreign_keys(index_engine)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()
    return state_engine, index_engine


def _v31_to_v30_downgrade_plan() -> Migration:
    """Build the explicit reverse of state_v30_to_v31_upgrade.

    Drops the three durable scan tables introduced in v30 -> v31 and rewinds
    schema_version to 30. This is a test-only construction that documents the
    rollback contract; production remains forward-only.
    """

    async def downgrade(conn) -> None:
        for table in DURABLE_TABLES:
            await conn.exec_driver_sql(f"DROP TABLE IF EXISTS {table}")

    return Migration(
        id="state_v31_to_v30_downgrade",
        from_version=31,
        to_version=30,
        upgrade=downgrade,
    )


async def _seed_production_data(state_engine) -> None:
    """Seed production data that must survive the downgrade."""
    factory = async_sessionmaker(state_engine, expire_on_commit=False)
    async with state_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO content_root_mappings "
                "(id, connection_id, content_type, display_name, alist_path, enabled, "
                "sort_order, home_order, created_at, updated_at) "
                "VALUES (901, 1, 'software', 'rollback-root', '/rb', 1, 0, 0, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
    async with factory() as session:
        existing = await session.get(SiteSettings, 1)
        if existing is None:
            session.add(SiteSettings(id=1, site_name="RollbackSurvivor"))
        else:
            existing.site_name = "RollbackSurvivor"
        await session.commit()


async def _table_exists(conn, table: str) -> bool:
    row = await conn.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=:n",
        {"n": table},
    )
    return row.fetchone() is not None


async def test_v31_downgrade_plan_exists():
    """The v31 -> v30 downgrade plan is well-formed."""
    plan = _v31_to_v30_downgrade_plan()
    assert plan.id == "state_v31_to_v30_downgrade"
    assert plan.from_version == 31
    assert plan.to_version == 30
    assert callable(plan.upgrade)


async def test_downgrade_preserves_data(tmp_path, monkeypatch):
    """Downgrade drops only durable scan tables; production data survives."""
    state_engine, index_engine = await _init_engines(tmp_path, monkeypatch)
    try:
        await _seed_production_data(state_engine)

        async with state_engine.begin() as conn:
            await _v31_to_v30_downgrade_plan().upgrade(conn)
            await set_state_schema_version(conn, 30)

        async with state_engine.connect() as conn:
            assert await get_state_schema_version(conn) == 30
            roots = (
                await conn.execute(
                    text(
                        "SELECT display_name FROM content_root_mappings WHERE id=901"
                    )
                )
            ).scalar_one_or_none()
            assert roots == "rollback-root"
            site_name = (
                await conn.execute(
                    text("SELECT site_name FROM site_settings WHERE id=1")
                )
            ).scalar_one_or_none()
            assert site_name == "RollbackSurvivor"
    finally:
        await state_engine.dispose()
        await index_engine.dispose()


async def test_downgrade_drops_durable_scan_tables(tmp_path, monkeypatch):
    """Downgrade removes the three durable scan tables."""
    state_engine, index_engine = await _init_engines(tmp_path, monkeypatch)
    try:
        async with state_engine.connect() as conn:
            for table in DURABLE_TABLES:
                assert await _table_exists(conn, table), f"precondition: {table} missing"

        async with state_engine.begin() as conn:
            await _v31_to_v30_downgrade_plan().upgrade(conn)
            await set_state_schema_version(conn, 30)

        async with state_engine.connect() as conn:
            for table in DURABLE_TABLES:
                assert not await _table_exists(conn, table), (
                    f"downgrade did not drop {table}"
                )
    finally:
        await state_engine.dispose()
        await index_engine.dispose()


async def test_reupgrade_after_downgrade(tmp_path, monkeypatch):
    """After downgrade to v30, re-running init_databases re-upgrades to v31."""
    state_engine, index_engine = await _init_engines(tmp_path, monkeypatch)
    try:
        await _seed_production_data(state_engine)

        async with state_engine.begin() as conn:
            await _v31_to_v30_downgrade_plan().upgrade(conn)
            await set_state_schema_version(conn, 30)

        async with state_engine.connect() as conn:
            assert await get_state_schema_version(conn) == 30
            for table in DURABLE_TABLES:
                assert not await _table_exists(conn, table)

        await state_engine.dispose()
        await index_engine.dispose()

        state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
        index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
        _enable_foreign_keys(state_engine)
        _enable_foreign_keys(index_engine)
        monkeypatch.setattr(database, "state_engine", state_engine)
        monkeypatch.setattr(database, "index_engine", index_engine)
        await database.init_databases()

        async with state_engine.connect() as conn:
            assert await get_state_schema_version(conn) == CURRENT_SCHEMA_VERSION
            for table in DURABLE_TABLES:
                assert await _table_exists(conn, table), (
                    f"re-upgrade did not recreate {table}"
                )
            roots = (
                await conn.execute(
                    text(
                        "SELECT display_name FROM content_root_mappings WHERE id=901"
                    )
                )
            ).scalar_one_or_none()
            assert roots == "rollback-root"
    finally:
        await state_engine.dispose()
        await index_engine.dispose()


async def test_migration_idempotent(tmp_path, monkeypatch):
    """Running init_databases twice does not raise and schema_version is stable."""
    state_engine, index_engine = await _init_engines(tmp_path, monkeypatch)
    try:
        async with state_engine.connect() as conn:
            assert await get_state_schema_version(conn) == CURRENT_SCHEMA_VERSION
    finally:
        await state_engine.dispose()
        await index_engine.dispose()

    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    _enable_foreign_keys(state_engine)
    _enable_foreign_keys(index_engine)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    try:
        await database.init_databases()
        async with state_engine.connect() as conn:
            assert await get_state_schema_version(conn) == CURRENT_SCHEMA_VERSION
            for table in DURABLE_TABLES:
                assert await _table_exists(conn, table), (
                    f"idempotent re-init lost {table}"
                )
    finally:
        await state_engine.dispose()
        await index_engine.dispose()
