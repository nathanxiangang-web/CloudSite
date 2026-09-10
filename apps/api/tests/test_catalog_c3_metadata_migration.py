"""Focused smoke tests for the C3 Catalog metadata overlay (tags, relations,
revisions) state model.

Covers the persistence boundary only:
- fresh initialization reaches schema v5 and creates the four new tables
  (catalog_tags, catalog_tag_assignments, catalog_relations, catalog_revisions)
  plus the append-only triggers on catalog_revisions
- a synthetic v1.1 (schema_version=4) state.db upgrades to v5 with the four
  new tables, and existing C1 catalog rows survive the upgrade
- repeated initialization is idempotent (no duplicate tables/indexes/triggers,
  version stable)
- constraints reject duplicate normalized tag slugs, duplicate entry-tag
  membership, duplicate typed relations, and direct self-relations
  deterministically
- catalog_revisions is append-only: UPDATE and DELETE are rejected, and a later
  rollback is representable as a new revision row
- revision rows persist structured before/after snapshots, diff, base/resulting
  revision, summary, actor, source, and timestamps, independent from index.db

Full API, recovery, and cross-version regression are deferred to the
verification phase.
"""
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import database, models  # noqa: F401 - register ORM metadata
from cloudsite.database import IndexBase, StateBase
from cloudsite.migrations import (
    CURRENT_SCHEMA_VERSION,
    get_state_schema_version,
)

C3_TABLES = (
    "catalog_tags",
    "catalog_tag_assignments",
    "catalog_relations",
    "catalog_revisions",
)


def _engines(tmp_path):
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    return state_engine, index_engine


async def _table_names(conn) -> set[str]:
    return await conn.run_sync(lambda sync_conn: set(inspect(sync_conn).get_table_names()))


async def _index_names(conn, table: str) -> set[str]:
    return await conn.run_sync(
        lambda sync_conn: {ix["name"] for ix in inspect(sync_conn).get_indexes(table)}
    )


async def _trigger_names(conn) -> set[str]:
    rows = await conn.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='catalog_revisions'"
    )
    return {row[0] for row in rows.fetchall()}


async def test_empty_init_creates_c3_tables_and_triggers(tmp_path, monkeypatch):
    """Fresh databases reach schema v6 and contain the four C3 tables and
    the append-only triggers on catalog_revisions."""
    state_engine, index_engine = _engines(tmp_path)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)

    await database.init_databases()

    async with state_engine.connect() as conn:
        assert await get_state_schema_version(conn) == CURRENT_SCHEMA_VERSION
        assert CURRENT_SCHEMA_VERSION == 12
        tables = await _table_names(conn)
        for table in C3_TABLES:
            assert table in tables, f"missing table {table}"
        triggers = await _trigger_names(conn)
        assert "catalog_revisions_no_update" in triggers
        assert "catalog_revisions_no_delete" in triggers
        tag_columns = await conn.run_sync(
            lambda sync_conn: {
                column["name"]: column for column in inspect(sync_conn).get_columns("catalog_tags")
            }
        )
        assert "slug" in tag_columns
        assert "display_name" in tag_columns

    await state_engine.dispose()
    await index_engine.dispose()


async def test_synthetic_v4_upgrades_to_v5_preserving_c1_rows(tmp_path, monkeypatch):
    """A synthetic v1.1 (schema_version=4) state.db with existing C1 catalog
    rows upgrades to v5 with the four new C3 tables, and C1 rows survive."""
    state_engine, index_engine = _engines(tmp_path)

    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
        await conn.execute(
            text(
                "INSERT OR REPLACE INTO system_settings(key, value, value_type, updated_at) "
                "VALUES('schema_version', '4', 'integer', CURRENT_TIMESTAMP)"
            )
        )
    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)

    from sqlalchemy.ext.asyncio import async_sessionmaker
    factory = async_sessionmaker(state_engine, expire_on_commit=False)
    async with factory() as session:
        session.add(
            models.CatalogEntry(
                entry_id="ce_survive",
                content_type="software",
                slug="survivor",
                title="Survivor",
                status="published",
                revision=3,
            )
        )
        await session.commit()

    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    async with state_engine.connect() as conn:
        assert await get_state_schema_version(conn) == CURRENT_SCHEMA_VERSION
        tables = await _table_names(conn)
        for table in C3_TABLES:
            assert table in tables
        for table in C3_TABLES:
            count = (await conn.execute(text(f"SELECT COUNT(*) FROM {table}"))).scalar_one()
            assert count == 0
        entry_title = (
            await conn.execute(text("SELECT title FROM catalog_entries WHERE entry_id='ce_survive'"))
        ).scalar_one()
        assert entry_title == "Survivor"

    await state_engine.dispose()
    await index_engine.dispose()


async def test_repeated_init_is_idempotent_c3(tmp_path, monkeypatch):
    """Re-running initialization does not duplicate C3 tables, indexes, or
    triggers and keeps version stable at v5."""
    state_engine, index_engine = _engines(tmp_path)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)

    await database.init_databases()

    async with state_engine.connect() as conn:
        indexes_before = {table: await _index_names(conn, table) for table in C3_TABLES}
        triggers_before = await _trigger_names(conn)

    await database.init_databases()
    await database.init_databases()

    async with state_engine.connect() as conn:
        assert await get_state_schema_version(conn) == CURRENT_SCHEMA_VERSION
        for table in C3_TABLES:
            indexes_after = await _index_names(conn, table)
            assert indexes_after == indexes_before[table], (
                f"index set changed for {table}: {indexes_before[table]} -> {indexes_after}"
            )
        triggers_after = await _trigger_names(conn)
        assert triggers_after == triggers_before

    await state_engine.dispose()
    await index_engine.dispose()


async def test_duplicate_normalized_tag_slug_rejected(tmp_path, monkeypatch):
    """Duplicate catalog_tags.slug is rejected by the unique constraint."""
    state_engine, index_engine = _engines(tmp_path)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    factory = async_sessionmaker(state_engine, expire_on_commit=False)
    async with factory() as session:
        session.add(models.CatalogTag(tag_id="ct_" + "a" * 32, slug="lts", display_name="LTS"))
        await session.commit()

    async with factory() as session:
        session.add(
            models.CatalogTag(
                tag_id="ct_" + "b" * 32, slug="LTS", display_name="Long Term Support"
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()

    await state_engine.dispose()
    await index_engine.dispose()


async def test_duplicate_entry_tag_membership_rejected(tmp_path, monkeypatch):
    """Duplicate (tag_id, target_type, target_id) membership is rejected."""
    state_engine, index_engine = _engines(tmp_path)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    factory = async_sessionmaker(state_engine, expire_on_commit=False)
    tag_id = "ct_" + "c" * 32
    async with factory() as session:
        session.add(models.CatalogTag(tag_id=tag_id, slug="stable", display_name="Stable"))
        session.add(
            models.CatalogTagAssignment(
                tag_id=tag_id, target_type="entry", target_id="ce_" + "d" * 32
            )
        )
        await session.commit()

    async with factory() as session:
        session.add(
            models.CatalogTagAssignment(
                tag_id=tag_id, target_type="entry", target_id="ce_" + "d" * 32
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()

    await state_engine.dispose()
    await index_engine.dispose()


async def test_duplicate_typed_relation_rejected(tmp_path, monkeypatch):
    """Duplicate (from_entry_id, to_entry_id, relation_type) is rejected."""
    state_engine, index_engine = _engines(tmp_path)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    factory = async_sessionmaker(state_engine, expire_on_commit=False)
    from_id = "ce_" + "e" * 32
    to_id = "ce_" + "f" * 32
    async with factory() as session:
        session.add(
            models.CatalogEntry(entry_id=from_id, content_type="software", slug="from", title="From")
        )
        session.add(
            models.CatalogEntry(entry_id=to_id, content_type="software", slug="to", title="To")
        )
        session.add(
            models.CatalogRelation(
                relation_id="cx_" + "1" * 32,
                from_entry_id=from_id,
                to_entry_id=to_id,
                relation_type="supersedes",
            )
        )
        await session.commit()

    async with factory() as session:
        session.add(
            models.CatalogRelation(
                relation_id="cx_" + "2" * 32,
                from_entry_id=from_id,
                to_entry_id=to_id,
                relation_type="supersedes",
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()

    await state_engine.dispose()
    await index_engine.dispose()


async def test_direct_self_relation_rejected(tmp_path, monkeypatch):
    """A relation with from_entry_id == to_entry_id is rejected by the CHECK
    constraint at the database boundary."""
    state_engine, index_engine = _engines(tmp_path)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    factory = async_sessionmaker(state_engine, expire_on_commit=False)
    entry_id = "ce_" + "g" * 32
    async with factory() as session:
        session.add(
            models.CatalogEntry(entry_id=entry_id, content_type="software", slug="self", title="Self")
        )
        await session.commit()

    async with factory() as session:
        session.add(
            models.CatalogRelation(
                relation_id="cx_" + "3" * 32,
                from_entry_id=entry_id,
                to_entry_id=entry_id,
                relation_type="variant",
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()

    await state_engine.dispose()
    await index_engine.dispose()


async def test_revision_append_only_rejects_update_and_delete(tmp_path, monkeypatch):
    """catalog_revisions is append-only: UPDATE and DELETE are rejected by
    triggers. A later rollback is represented as a new revision row."""
    state_engine, index_engine = _engines(tmp_path)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    factory = async_sessionmaker(state_engine, expire_on_commit=False)
    rev_id = "cv_" + "a" * 32
    async with factory() as session:
        session.add(
            models.CatalogRevision(
                revision_id=rev_id,
                target_type="entry",
                target_id="ce_" + "h" * 32,
                action="create",
                actor="admin",
                source="admin",
                base_revision=None,
                resulting_revision=1,
                summary="initial create",
                before_json="{}",
                after_json='{"title":"A"}',
                diff_json='{"title":["__missing__","A"]}',
            )
        )
        await session.commit()

    async with state_engine.begin() as conn:
        with pytest.raises(Exception):
            await conn.execute(
                text(f"UPDATE catalog_revisions SET summary='tampered' WHERE revision_id='{rev_id}'")
            )

    async with state_engine.begin() as conn:
        with pytest.raises(Exception):
            await conn.execute(
                text(f"DELETE FROM catalog_revisions WHERE revision_id='{rev_id}'")
            )

    async with factory() as session:
        session.add(
            models.CatalogRevision(
                revision_id="cv_" + "b" * 32,
                target_type="entry",
                target_id="ce_" + "h" * 32,
                action="update",
                actor="admin",
                source="admin",
                base_revision=1,
                resulting_revision=2,
                summary="rollback to draft",
                before_json='{"title":"A"}',
                after_json='{"title":"A","status":"draft"}',
                diff_json='{"status":["published","draft"]}',
            )
        )
        await session.commit()

    async with state_engine.connect() as conn:
        count = (
            await conn.execute(
                text("SELECT COUNT(*) FROM catalog_revisions WHERE target_id='ce_" + "h" * 32 + "'")
            )
        ).scalar_one()
        assert count == 2

    await state_engine.dispose()
    await index_engine.dispose()


async def test_revision_persists_structured_snapshots_independent_of_index(tmp_path, monkeypatch):
    """Revision rows persist structured before/after/diff, base/resulting
    revision, summary, actor, source, and timestamps. Deleting index.db does
    not touch revision state in state.db."""
    state_engine, index_engine = _engines(tmp_path)
    monkeypatch.setattr(database, "state_engine", state_engine)
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    factory = async_sessionmaker(state_engine, expire_on_commit=False)
    rev_id = "cv_" + "c" * 32
    async with factory() as session:
        session.add(
            models.CatalogRevision(
                revision_id=rev_id,
                target_type="entry",
                target_id="ce_" + "i" * 32,
                action="publish",
                actor="admin",
                source="admin",
                base_revision=1,
                resulting_revision=2,
                summary="published entry",
                before_json='{"status":"draft"}',
                after_json='{"status":"published"}',
                diff_json='{"status":["draft","published"]}',
                payload_json='{"note":"go-live"}',
            )
        )
        await session.commit()

    (tmp_path / "index.db").unlink()
    await index_engine.dispose()
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    monkeypatch.setattr(database, "index_engine", index_engine)
    await database.init_databases()

    async with state_engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT target_type, target_id, action, actor, source, base_revision, "
                    "resulting_revision, summary, before_json, after_json, diff_json, "
                    "payload_json FROM catalog_revisions WHERE revision_id=:rid"
                ),
                {"rid": rev_id},
            )
        ).one()
        assert row[0] == "entry"
        assert row[1] == "ce_" + "i" * 32
        assert row[2] == "publish"
        assert row[3] == "admin"
        assert row[4] == "admin"
        assert row[5] == 1
        assert row[6] == 2
        assert row[7] == "published entry"
        assert row[8] == '{"status":"draft"}'
        assert row[9] == '{"status":"published"}'
        assert row[10] == '{"status":["draft","published"]}'
        assert row[11] == '{"note":"go-live"}'

    await state_engine.dispose()
    await index_engine.dispose()
