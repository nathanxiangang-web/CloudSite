"""P0-2 FTS delta for _resolve_pending_for_parent resolved_move/resolved_new."""
from datetime import datetime, timezone
from dataclasses import dataclass, field

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import search
from cloudsite.database import IndexBase, StateBase
from cloudsite.identity.schemas import IdentityResolution
from cloudsite.models import (
    Folder,
    Resource,
    ResourceIdentityCandidate,
    SyncCycle,
    SyncRun,
)
from cloudsite.sync import rolling


async def _make_factories(monkeypatch):
    state_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    index_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    index_factory = async_sessionmaker(index_engine, expire_on_commit=False)
    async with state_engine.begin() as c:
        await c.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as c:
        await c.run_sync(IndexBase.metadata.create_all)
        await c.exec_driver_sql(
            "CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5("
            "object_id UNINDEXED, object_type UNINDEXED, name, extension, "
            "content_type UNINDEXED, description, tags, breadcrumb_text, "
            "tokenize=\'unicode61 remove_diacritics 2\')"
        )
    monkeypatch.setattr(rolling, "StateSession", state_factory)
    monkeypatch.setattr(rolling, "IndexSession", index_factory)
    monkeypatch.setattr(search, "StateSession", state_factory)
    monkeypatch.setattr(search, "IndexSession", index_factory)
    return state_engine, index_engine, state_factory, index_factory


async def test_resolved_move_produces_fts_update_op(monkeypatch):
    """resolved_move: _resolve_pending_for_parent returns FTS update op, apply updates search_fts."""
    state_engine, index_engine, _, index_factory = await _make_factories(monkeypatch)
    now = datetime(2026, 9, 6, tzinfo=timezone.utc)

    async with index_factory() as session:
        parent = Folder(id="parent", name="parent", path="/parent", parent_id=None,
                        content_type="software", root_mapping_id=1, depth=0, status="active")
        target = Folder(id="target", name="target", path="/target", parent_id=None,
                        content_type="software", root_mapping_id=1, depth=0, status="active")
        source = Resource(id="src-r", name="oldfile.txt", path="/parent/oldfile.txt",
                          parent_id="parent", content_type="software", root_mapping_id=1,
                          extension="txt", status="suspected_missing",
                          missing_last_observed_cycle_id=1)
        cycle = SyncCycle(id=1, cycle_type="normal", status="running", anchor_at=now,
                          planned_folder_count=1, windows_total=4)
        run = SyncRun(id=1, sync_type="rolling_window", status="running", roots_total=1)
        session.add_all([parent, target, source, cycle, run])
        await session.flush()

        session.add(ResourceIdentityCandidate(
            cycle_id=1, observed_path="/target/newfile.txt", observed_name="newfile.txt",
            observed_parent_id="target", root_mapping_id=1, content_type="software",
            matched_resource_id="src-r", status="pending", match_type="pending_move_or_copy",
            extension="txt", size=100, modified_at=now, fingerprint="fp",
        ))
        await session.execute(text(
            "INSERT INTO search_fts(object_id, object_type, name, extension, "
            "content_type, description, tags, breadcrumb_text) VALUES "
            "(\'src-r\',\'resource\',\'oldfile.txt\',\'txt\',\'software\',\'\',\'\',\'/parent/oldfile.txt\')"
        ))
        await session.commit()

    async def mock_resolve(session, observations, **kwargs):
        return [IdentityResolution(observation=observations[0], resource_id="src-r", match_type="confirmed", fingerprint="fp")]

    monkeypatch.setattr(rolling, "resolve_resource_identities", mock_resolve)

    async with index_factory() as session:
        parent = await session.get(Folder, "parent")
        cycle = await session.get(SyncCycle, 1)
        run = await session.get(SyncRun, 1)
        result = await rolling._resolve_pending_for_parent(session, cycle, run, parent, now)

        assert result["updated"] == 1
        assert result["added"] == 0
        assert len(result["fts_ops"]) == 1
        assert result["fts_ops"][0].op_type == "update"
        assert result["fts_ops"][0].object_id == "src-r"

        await search.apply_search_fts_delta(session, result["fts_ops"])
        await session.commit()

    async with index_factory() as session:
        row = (await session.execute(text(
            "SELECT name, breadcrumb_text FROM search_fts WHERE object_id=\'src-r\'"
        ))).fetchone()
        assert row is not None
        assert row[0] == "newfile.txt"
        assert row[1] == "/target/newfile.txt"

    await state_engine.dispose()
    await index_engine.dispose()


async def test_resolved_new_produces_fts_insert_op(monkeypatch):
    """resolved_new: _resolve_pending_for_parent returns FTS insert op, apply inserts into search_fts."""
    state_engine, index_engine, _, index_factory = await _make_factories(monkeypatch)
    now = datetime(2026, 9, 6, tzinfo=timezone.utc)

    async with index_factory() as session:
        parent = Folder(id="parent", name="parent", path="/parent", parent_id=None,
                        content_type="software", root_mapping_id=1, depth=0, status="active")
        target = Folder(id="target", name="target", path="/target", parent_id=None,
                        content_type="software", root_mapping_id=1, depth=0, status="active")
        source = Resource(id="src-r", name="oldfile.txt", path="/parent/oldfile.txt",
                          parent_id="parent", content_type="software", root_mapping_id=1,
                          extension="txt", status="active")
        cycle = SyncCycle(id=1, cycle_type="normal", status="running", anchor_at=now,
                          planned_folder_count=1, windows_total=4)
        run = SyncRun(id=1, sync_type="rolling_window", status="running", roots_total=1)
        session.add_all([parent, target, source, cycle, run])
        await session.flush()

        session.add(ResourceIdentityCandidate(
            cycle_id=1, observed_path="/target/newfile.txt", observed_name="newfile.txt",
            observed_parent_id="target", root_mapping_id=1, content_type="software",
            matched_resource_id="src-r", status="pending", match_type="pending_move_or_copy",
            extension="txt", size=100, modified_at=now, fingerprint="fp",
        ))
        await session.commit()

    async def mock_resolve(session, observations, **kwargs):
        return [IdentityResolution(observation=observations[0], resource_id="new-r", match_type="confirmed", fingerprint="fp")]

    monkeypatch.setattr(rolling, "resolve_resource_identities", mock_resolve)

    async with index_factory() as session:
        parent = await session.get(Folder, "parent")
        cycle = await session.get(SyncCycle, 1)
        run = await session.get(SyncRun, 1)
        result = await rolling._resolve_pending_for_parent(session, cycle, run, parent, now)

        assert result["added"] == 1
        assert result["updated"] == 0
        assert len(result["fts_ops"]) == 1
        assert result["fts_ops"][0].op_type == "insert"
        assert result["fts_ops"][0].object_id == "new-r"

        await search.apply_search_fts_delta(session, result["fts_ops"])
        await session.commit()

    async with index_factory() as session:
        row = (await session.execute(text(
            "SELECT name, breadcrumb_text FROM search_fts WHERE object_id=\'new-r\'"
        ))).fetchone()
        assert row is not None
        assert row[0] == "newfile.txt"
        assert row[1] == "/target/newfile.txt"

    await state_engine.dispose()
    await index_engine.dispose()
