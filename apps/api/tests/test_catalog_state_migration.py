"""Focused smoke tests for the C1 Catalog core state model.

Covers the persistence boundary only:
- empty initialization reaches the new schema version and creates the four tables
- synthetic v1.0 (schema_version=3) state.db upgrades to v4 with the four tables
- repeated initialization is idempotent (no duplicate tables/indexes, version stable)
- durable Catalog rows survive index.db deletion and rebuild, and catalog_locations.resource_id
  is a plain cross-database value with no SQL foreign key to index.db

Full API, recovery, and cross-version regression are deferred to the verification phase.
"""
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from cloudsite import database, models  # noqa: F401 - register ORM metadata
from cloudsite.database import IndexBase, StateBase
from cloudsite.migrations import (
    CURRENT_SCHEMA_VERSION,
    get_state_schema_version,
    get_index_schema_version,
)

CATALOG_TABLES = (
    "catalog_entries",
    "catalog_releases",
    "catalog_assets",
    "catalog_locations",
)


def _engines(tmp_path):
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    return state_engine, index_engine


async def _table_names(conn) -> set[str]:
    names = await conn.run_sync(lambda sync_conn: set(inspect(sync_conn).get_table_names()))
    return names


async def _index_names(conn, table: str) -> set[str]:
    return await conn.run_sync(
        lambda sync_conn: {ix["name"] for ix in inspect(sync_conn).get_indexes(table)}
    )


async def _fk_targets(conn, table: str) -> set[tuple[str, str]]:
    """Return set of (referred_table, referred_column) for FKs declared on table."""
    return await conn.run_sync(
        lambda sync_conn: {
            (fk["referred_table"], tuple(fk["referred_columns"]))
            for fk in inspect(sync_conn).get_foreign_keys(table)
        }
    )


async def test_empty_init_creates_catalog_tables(tmp_path, monkeypatch):
    """Fresh databases reach the new schema version and contain the four tables."""
    state_engine, index_engine = _engines(tmp_path)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)

    await database.init_databases()

    async with state_engine.connect() as conn:
        assert await get_state_schema_version(conn) == CURRENT_SCHEMA_VERSION
        tables = await _table_names(conn)
        for table in CATALOG_TABLES:
            assert table in tables, f"missing table {table}"
        entry_columns = await conn.run_sync(
            lambda sync_conn: {
                column["name"]: column for column in inspect(sync_conn).get_columns("catalog_entries")
            }
        )
        assert "revision" in entry_columns
        assert str(entry_columns["revision"]["default"]).strip("'\"") == "1"
    async with index_engine.connect() as conn:
        assert await get_index_schema_version(conn) == CURRENT_SCHEMA_VERSION

    await state_engine.dispose()
    await index_engine.dispose()


async def test_synthetic_v3_upgrades_to_v4(tmp_path, monkeypatch):
    """A synthetic v1.0 (schema_version=3) state.db upgrades to v4 with catalog tables."""
    state_engine, index_engine = _engines(tmp_path)

    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
        await conn.execute(
            text(
                "INSERT OR REPLACE INTO system_settings(key, value, value_type, updated_at) "
                "VALUES('schema_version', '3', 'integer', CURRENT_TIMESTAMP)"
            )
        )
    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)

    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    async with state_engine.connect() as conn:
        assert await get_state_schema_version(conn) == CURRENT_SCHEMA_VERSION
        tables = await _table_names(conn)
        for table in CATALOG_TABLES:
            assert table in tables
        # catalog tables must be empty after migration (no auto backfill)
        for table in CATALOG_TABLES:
            count = (await conn.execute(text(f"SELECT COUNT(*) FROM {table}"))).scalar_one()
            assert count == 0

    await state_engine.dispose()
    await index_engine.dispose()


async def test_repeated_init_is_idempotent(tmp_path, monkeypatch):
    """Re-running initialization does not duplicate tables or indexes and keeps version stable."""
    state_engine, index_engine = _engines(tmp_path)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)

    await database.init_databases()

    async with state_engine.connect() as conn:
        catalog_indexes_before = {
            table: await _index_names(conn, table) for table in CATALOG_TABLES
        }

    await database.init_databases()
    await database.init_databases()

    async with state_engine.connect() as conn:
        assert await get_state_schema_version(conn) == CURRENT_SCHEMA_VERSION
        for table in CATALOG_TABLES:
            indexes_after = await _index_names(conn, table)
            assert indexes_after == catalog_indexes_before[table], (
                f"index set changed for {table}: {catalog_indexes_before[table]} -> {indexes_after}"
            )

    await state_engine.dispose()
    await index_engine.dispose()


async def test_catalog_rows_survive_index_rebuild(tmp_path, monkeypatch):
    """Durable Catalog rows survive index.db deletion and rebuild.

    catalog_locations.resource_id is a plain stable ID with no SQL foreign key
    to index.db, so deleting and rebuilding index.db must not touch catalog state.
    """
    state_engine, index_engine = _engines(tmp_path)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)

    await database.init_databases()

    from sqlalchemy.ext.asyncio import async_sessionmaker
    from cloudsite.models import (
        CatalogAsset,
        CatalogEntry,
        CatalogLocation,
        CatalogRelease,
    )

    factory = async_sessionmaker(state_engine, expire_on_commit=False)
    async with factory() as session:
        entry = CatalogEntry(
            entry_id="ce_" + "a" * 32,
            content_type="software",
            slug="ubuntu-22-04-lts",
            title="Ubuntu 22.04 LTS",
            status="published",
        )
        release = CatalogRelease(
            release_id="cr_" + "b" * 32,
            entry_id=entry.entry_id,
            slug="22.04.3",
            title="22.04.3",
            status="published",
        )
        asset = CatalogAsset(
            asset_id="ca_" + "c" * 32,
            release_id=release.release_id,
            slug="amd64-iso",
            display_name="ubuntu-22.04.3-desktop-amd64.iso",
            kind="file",
        )
        location = CatalogLocation(
            location_id="cl_" + "d" * 32,
            asset_id=asset.asset_id,
            resource_id="r_" + "e" * 32,
            root_mapping_id=1,
            is_primary=True,
        )
        session.add_all([entry, release, asset, location])
        await session.commit()

    # Delete index.db, dispose the stale engine, and rebuild with a fresh engine.
    # This simulates a process restart after index.db loss: the new engine creates
    # a fresh index.db while state.db catalog rows must remain intact.
    (tmp_path / "index.db").unlink()
    await index_engine.dispose()
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    async with state_engine.connect() as conn:
        assert await get_state_schema_version(conn) == CURRENT_SCHEMA_VERSION
        entry_count = (await conn.execute(text("SELECT COUNT(*) FROM catalog_entries"))).scalar_one()
        release_count = (await conn.execute(text("SELECT COUNT(*) FROM catalog_releases"))).scalar_one()
        asset_count = (await conn.execute(text("SELECT COUNT(*) FROM catalog_assets"))).scalar_one()
        location_count = (await conn.execute(text("SELECT COUNT(*) FROM catalog_locations"))).scalar_one()
        assert entry_count == 1
        assert release_count == 1
        assert asset_count == 1
        assert location_count == 1
        rid = (await conn.execute(text("SELECT resource_id FROM catalog_locations"))).scalar_one()
        assert rid == "r_" + "e" * 32

    await state_engine.dispose()
    await index_engine.dispose()


async def test_catalog_location_has_no_cross_db_foreign_key(tmp_path, monkeypatch):
    """catalog_locations.resource_id must not declare a SQL foreign key.

    The reference to index.db resources.id is by value only; no cross-SQLite FK.
    """
    state_engine, index_engine = _engines(tmp_path)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)

    await database.init_databases()

    async with state_engine.connect() as conn:
        fks = await _fk_targets(conn, "catalog_locations")
        # The only FK should be asset_id -> catalog_assets.asset_id (within state.db).
        assert ("catalog_assets", ("asset_id",)) in fks
        assert ("resources", ("id",)) not in fks
        assert len(fks) == 1

    await state_engine.dispose()
    await index_engine.dispose()


async def test_default_unversioned_release_slug(tmp_path, monkeypatch):
    """catalog_releases.slug defaults to 'unversioned' (explicit default representation)."""
    state_engine, index_engine = _engines(tmp_path)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)

    await database.init_databases()

    from sqlalchemy.ext.asyncio import async_sessionmaker
    from cloudsite.models import CatalogEntry, CatalogRelease

    factory = async_sessionmaker(state_engine, expire_on_commit=False)
    async with factory() as session:
        entry = CatalogEntry(
            entry_id="ce_" + "f" * 32,
            content_type="document",
            slug="guide",
            title="Guide",
        )
        release = CatalogRelease(
            release_id="cr_" + "0" * 32,
            entry_id=entry.entry_id,
            title="Default",
        )
        session.add_all([entry, release])
        await session.commit()

    async with state_engine.connect() as conn:
        slug = (await conn.execute(text("SELECT slug FROM catalog_releases WHERE release_id = :rid"),
                                    {"rid": "cr_" + "0" * 32})).scalar_one()
        assert slug == "unversioned"

    await state_engine.dispose()
    await index_engine.dispose()
