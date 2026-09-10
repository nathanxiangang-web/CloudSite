"""Focused tests for the C2 release and asset delivery metadata schema.

Covers the persistence boundary only:
- fresh initialization reaches schema v8 and creates the new release/asset
  columns with conservative defaults (channel='unknown', architecture='unknown',
  package_type='unknown', is_recommended=0)
- a synthetic v1.2 (schema_version=6) state.db with existing C1 catalog rows
  upgrades to v8, and C1 rows survive unchanged with conservative defaults
  (no inference from slugs or names)
- repeated initialization is idempotent (no duplicate columns/indexes, version
  stable)
- a second recommended release for the same entry is rejected at the database
  boundary by the partial unique index
- a caller can persist two releases with explicit channels and choose one
  recommendation without comparing version strings
- Windows x64 and ARM64 package rows under the same release remain distinct and
  queryable, and stable/beta/historical release records coexist

Full API, recovery, and cross-version regression are deferred to the
verification phase.
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import database, models  # noqa: F401 - register ORM metadata
from cloudsite.database import IndexBase, StateBase
from cloudsite.migrations import (
    CURRENT_SCHEMA_VERSION,
    get_state_schema_version,
    get_index_schema_version,
)


def _engines(tmp_path):
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    return state_engine, index_engine


async def _columns(conn, table: str) -> set[str]:
    return await conn.run_sync(
        lambda sync_conn: {column["name"] for column in inspect(sync_conn).get_columns(table)}
    )


async def _index_names(conn, table: str) -> set[str]:
    return await conn.run_sync(
        lambda sync_conn: {ix["name"] for ix in inspect(sync_conn).get_indexes(table)}
    )


async def test_fresh_init_creates_release_asset_metadata_columns(tmp_path, monkeypatch):
    """Fresh databases reach schema v8 and the new columns exist with conservative defaults."""
    state_engine, index_engine = _engines(tmp_path)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)

    await database.init_databases()

    async with state_engine.connect() as conn:
        assert await get_state_schema_version(conn) == CURRENT_SCHEMA_VERSION
        assert CURRENT_SCHEMA_VERSION == 15

        release_cols = await _columns(conn, "catalog_releases")
        for col in ("channel", "release_date", "is_recommended"):
            assert col in release_cols, f"missing catalog_releases column {col}"

        asset_cols = await _columns(conn, "catalog_assets")
        for col in ("architecture", "package_type", "language", "build_label"):
            assert col in asset_cols, f"missing catalog_assets column {col}"

        release_indexes = await _index_names(conn, "catalog_releases")
        assert "ux_catalog_releases_one_recommended_per_entry" in release_indexes

    # Use the ORM to insert rows so Python-side defaults apply, then verify the
    # conservative database defaults for the new metadata columns.
    factory = async_sessionmaker(state_engine, expire_on_commit=False)
    async with factory() as session:
        session.add(
            models.CatalogEntry(
                entry_id="ce_defaults",
                content_type="software",
                slug="defaults-entry",
                title="Defaults",
            )
        )
        session.add(
            models.CatalogRelease(
                release_id="cr_defaults",
                entry_id="ce_defaults",
                title="Default release",
            )
        )
        session.add(
            models.CatalogAsset(
                asset_id="ca_defaults",
                release_id="cr_defaults",
                slug="asset-default",
                display_name="Default asset",
            )
        )
        await session.commit()

    async with state_engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT channel, release_date, is_recommended "
                    "FROM catalog_releases WHERE release_id='cr_defaults'"
                )
            )
        ).one()
        assert row[0] == "unknown"
        assert row[1] is None
        assert row[2] in (0, False)

        asset_row = (
            await conn.execute(
                text(
                    "SELECT architecture, package_type, language, build_label "
                    "FROM catalog_assets WHERE asset_id='ca_defaults'"
                )
            )
        ).one()
        assert asset_row[0] == "unknown"
        assert asset_row[1] == "unknown"
        assert asset_row[2] == "unknown"
        assert asset_row[3] == ""

    async with index_engine.connect() as conn:
        assert await get_index_schema_version(conn) == CURRENT_SCHEMA_VERSION

    await state_engine.dispose()
    await index_engine.dispose()


async def test_synthetic_v6_upgrades_to_v7_preserving_c1_rows(tmp_path, monkeypatch):
    """A synthetic v1.2 (schema_version=6) state.db with existing C1 catalog rows
    upgrades to v8. C1 rows survive unchanged; new columns get conservative
    defaults with no inference from slugs or names."""
    state_engine, index_engine = _engines(tmp_path)

    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
        await conn.execute(
            text(
                "INSERT OR REPLACE INTO system_settings(key, value, value_type, updated_at) "
                "VALUES('schema_version', '6', 'integer', CURRENT_TIMESTAMP)"
            )
        )

    factory = async_sessionmaker(state_engine, expire_on_commit=False)
    async with factory() as session:
        entry = models.CatalogEntry(
            entry_id="ce_survive_c2",
            content_type="software",
            slug="legacy-tool",
            title="Legacy Tool",
            status="published",
            revision=2,
        )
        release = models.CatalogRelease(
            release_id="cr_survive_c2",
            entry_id=entry.entry_id,
            slug="1.0",
            title="1.0",
            status="published",
        )
        asset = models.CatalogAsset(
            asset_id="ca_survive_c2",
            release_id=release.release_id,
            slug="win-installer",
            display_name="LegacyInstaller.exe",
            kind="file",
        )
        session.add_all([entry, release, asset])
        await session.commit()

    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)

    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    async with state_engine.connect() as conn:
        assert await get_state_schema_version(conn) == CURRENT_SCHEMA_VERSION

        entry_title = (
            await conn.execute(
                text("SELECT title, revision FROM catalog_entries WHERE entry_id='ce_survive_c2'")
            )
        ).one()
        assert entry_title[0] == "Legacy Tool"
        assert entry_title[1] == 2

        release_row = (
            await conn.execute(
                text(
                    "SELECT slug, title, status, channel, release_date, is_recommended "
                    "FROM catalog_releases WHERE release_id='cr_survive_c2'"
                )
            )
        ).one()
        assert release_row[0] == "1.0"
        assert release_row[1] == "1.0"
        assert release_row[2] == "published"
        assert release_row[3] == "unknown"
        assert release_row[4] is None
        assert release_row[5] in (0, False)

        asset_row = (
            await conn.execute(
                text(
                    "SELECT slug, display_name, architecture, package_type, language, build_label "
                    "FROM catalog_assets WHERE asset_id='ca_survive_c2'"
                )
            )
        ).one()
        assert asset_row[0] == "win-installer"
        assert asset_row[1] == "LegacyInstaller.exe"
        assert asset_row[2] == "unknown"
        assert asset_row[3] == "unknown"
        assert asset_row[4] == "unknown"
        assert asset_row[5] == ""

    await state_engine.dispose()
    await index_engine.dispose()


async def test_repeated_init_is_idempotent_v8(tmp_path, monkeypatch):
    """Re-running initialization does not duplicate columns/indexes and keeps
    version stable at v8."""
    state_engine, index_engine = _engines(tmp_path)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)

    await database.init_databases()

    async with state_engine.connect() as conn:
        release_cols_before = await _columns(conn, "catalog_releases")
        release_idx_before = await _index_names(conn, "catalog_releases")
        asset_cols_before = await _columns(conn, "catalog_assets")
        asset_idx_before = await _index_names(conn, "catalog_assets")

    await database.init_databases()
    await database.init_databases()

    async with state_engine.connect() as conn:
        assert await get_state_schema_version(conn) == CURRENT_SCHEMA_VERSION
        assert await _columns(conn, "catalog_releases") == release_cols_before
        assert await _index_names(conn, "catalog_releases") == release_idx_before
        assert await _columns(conn, "catalog_assets") == asset_cols_before
        assert await _index_names(conn, "catalog_assets") == asset_idx_before

    await state_engine.dispose()
    await index_engine.dispose()


async def test_second_recommended_release_for_entry_rejected(tmp_path, monkeypatch):
    """A second recommended release for the same entry is rejected at the
    database boundary by the partial unique index."""
    state_engine, index_engine = _engines(tmp_path)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    factory = async_sessionmaker(state_engine, expire_on_commit=False)
    entry_id = "ce_reco_" + "a" * 24
    async with factory() as session:
        session.add(
            models.CatalogEntry(
                entry_id=entry_id,
                content_type="software",
                slug="reco-app",
                title="Reco App",
            )
        )
        session.add(
            models.CatalogRelease(
                release_id="cr_reco_1",
                entry_id=entry_id,
                slug="stable",
                title="Stable",
                channel="stable",
                is_recommended=True,
            )
        )
        await session.commit()

    async with factory() as session:
        session.add(
            models.CatalogRelease(
                release_id="cr_reco_2",
                entry_id=entry_id,
                slug="beta",
                title="Beta",
                channel="beta",
                is_recommended=True,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()

    async with factory() as session:
        session.add(
            models.CatalogRelease(
                release_id="cr_reco_2",
                entry_id=entry_id,
                slug="beta",
                title="Beta",
                channel="beta",
                is_recommended=False,
            )
        )
        await session.commit()

    async with state_engine.connect() as conn:
        count = (
            await conn.execute(
                text(
                    "SELECT COUNT(*) FROM catalog_releases "
                    "WHERE entry_id=:eid AND is_recommended=1"
                ),
                {"eid": entry_id},
            )
        ).scalar_one()
        assert count == 1

    await state_engine.dispose()
    await index_engine.dispose()


async def test_recommendation_choice_without_version_comparison(tmp_path, monkeypatch):
    """A caller can persist two releases with explicit channels and choose one
    recommendation without comparing version strings."""
    state_engine, index_engine = _engines(tmp_path)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    factory = async_sessionmaker(state_engine, expire_on_commit=False)
    entry_id = "ce_choice_" + "b" * 22
    async with factory() as session:
        session.add(
            models.CatalogEntry(
                entry_id=entry_id,
                content_type="software",
                slug="choice-app",
                title="Choice App",
            )
        )
        session.add(
            models.CatalogRelease(
                release_id="cr_choice_stable",
                entry_id=entry_id,
                slug="100",
                title="100",
                channel="stable",
                is_recommended=True,
                sort_order=0,
            )
        )
        session.add(
            models.CatalogRelease(
                release_id="cr_choice_beta",
                entry_id=entry_id,
                slug="200",
                title="200",
                channel="beta",
                is_recommended=False,
                sort_order=1,
            )
        )
        await session.commit()

    async with state_engine.connect() as conn:
        recommended = (
            await conn.execute(
                text(
                    "SELECT release_id, channel FROM catalog_releases "
                    "WHERE entry_id=:eid AND is_recommended=1"
                ),
                {"eid": entry_id},
            )
        ).one()
        assert recommended[0] == "cr_choice_stable"
        assert recommended[1] == "stable"

        channels = {
            row[0]
            for row in (
                await conn.execute(
                    text("SELECT channel FROM catalog_releases WHERE entry_id=:eid"),
                    {"eid": entry_id},
                )
            ).all()
        }
        assert channels == {"stable", "beta"}

    await state_engine.dispose()
    await index_engine.dispose()


async def test_x64_and_arm64_assets_distinct_and_queryable(tmp_path, monkeypatch):
    """Windows x64 and ARM64 package rows under the same release remain distinct
    and queryable by architecture and package_type."""
    state_engine, index_engine = _engines(tmp_path)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    factory = async_sessionmaker(state_engine, expire_on_commit=False)
    entry_id = "ce_multiarch_" + "c" * 20
    release_id = "cr_multiarch_" + "d" * 20
    async with factory() as session:
        session.add(
            models.CatalogEntry(
                entry_id=entry_id,
                content_type="software",
                slug="multiarch-app",
                title="MultiArch App",
            )
        )
        session.add(
            models.CatalogRelease(
                release_id=release_id,
                entry_id=entry_id,
                slug="1.0.0",
                title="1.0.0",
                channel="stable",
            )
        )
        session.add(
            models.CatalogAsset(
                asset_id="ca_x64",
                release_id=release_id,
                slug="windows-x64-installer",
                display_name="App-1.0.0-x64.msi",
                platform="windows",
                kind="file",
                architecture="x64",
                package_type="installer",
                checksum="abc123",
                checksum_algorithm="sha256",
                size=10_000_000,
            )
        )
        session.add(
            models.CatalogAsset(
                asset_id="ca_arm64",
                release_id=release_id,
                slug="windows-arm64-installer",
                display_name="App-1.0.0-arm64.msi",
                platform="windows",
                kind="file",
                architecture="arm64",
                package_type="installer",
                checksum="def456",
                checksum_algorithm="sha256",
                size=9_500_000,
            )
        )
        await session.commit()

    async with state_engine.connect() as conn:
        total = (
            await conn.execute(
                text("SELECT COUNT(*) FROM catalog_assets WHERE release_id=:rid"),
                {"rid": release_id},
            )
        ).scalar_one()
        assert total == 2

        x64 = (
            await conn.execute(
                text(
                    "SELECT asset_id, architecture, package_type, size "
                    "FROM catalog_assets WHERE release_id=:rid AND architecture='x64'"
                ),
                {"rid": release_id},
            )
        ).one()
        assert x64[0] == "ca_x64"
        assert x64[1] == "x64"
        assert x64[2] == "installer"
        assert x64[3] == 10_000_000

        arm64 = (
            await conn.execute(
                text(
                    "SELECT asset_id, architecture, package_type, size "
                    "FROM catalog_assets WHERE release_id=:rid AND architecture='arm64'"
                ),
                {"rid": release_id},
            )
        ).one()
        assert arm64[0] == "ca_arm64"
        assert arm64[1] == "arm64"
        assert arm64[2] == "installer"
        assert arm64[3] == 9_500_000

        installers = (
            await conn.execute(
                text(
                    "SELECT COUNT(*) FROM catalog_assets "
                    "WHERE release_id=:rid AND package_type='installer'"
                ),
                {"rid": release_id},
            )
        ).scalar_one()
        assert installers == 2

    await state_engine.dispose()
    await index_engine.dispose()


async def test_stable_beta_historical_releases_coexist(tmp_path, monkeypatch):
    """stable, beta, and historical release records coexist under one entry with
    explicit channels and an optional release date."""
    state_engine, index_engine = _engines(tmp_path)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    factory = async_sessionmaker(state_engine, expire_on_commit=False)
    entry_id = "ce_channels_" + "e" * 20
    async with factory() as session:
        session.add(
            models.CatalogEntry(
                entry_id=entry_id,
                content_type="software",
                slug="channel-app",
                title="Channel App",
            )
        )
        session.add(
            models.CatalogRelease(
                release_id="cr_ch_stable",
                entry_id=entry_id,
                slug="stable",
                title="Stable",
                channel="stable",
                is_recommended=True,
                release_date=datetime(2026, 1, 15, tzinfo=timezone.utc),
            )
        )
        session.add(
            models.CatalogRelease(
                release_id="cr_ch_beta",
                entry_id=entry_id,
                slug="beta",
                title="Beta",
                channel="beta",
                is_recommended=False,
                release_date=datetime(2026, 3, 1, tzinfo=timezone.utc),
            )
        )
        session.add(
            models.CatalogRelease(
                release_id="cr_ch_historical",
                entry_id=entry_id,
                slug="legacy",
                title="Legacy",
                channel="historical",
                is_recommended=False,
                release_date=datetime(2025, 6, 1, tzinfo=timezone.utc),
            )
        )
        await session.commit()

    async with state_engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT channel, is_recommended, release_date "
                    "FROM catalog_releases WHERE entry_id=:eid "
                    "ORDER BY channel"
                ),
                {"eid": entry_id},
            )
        ).all()
        channels = [r[0] for r in rows]
        assert channels == ["beta", "historical", "stable"]
        recommended = [r for r in rows if r[1] in (1, True)]
        assert len(recommended) == 1
        assert recommended[0][0] == "stable"
        stable_date = [r[2] for r in rows if r[0] == "stable"][0]
        assert stable_date is not None

    await state_engine.dispose()
    await index_engine.dispose()
