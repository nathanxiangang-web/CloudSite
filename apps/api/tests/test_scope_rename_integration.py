"""P0-4/P0-1/P0-2b/P1-2 scope rename integration tests."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import search
from cloudsite.database import IndexBase, StateBase
from cloudsite.models import (
    Folder,
    FolderScanState,
    Resource,
    SyncChange,
    SyncCycle,
    SyncCycleItem,
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


def _entry(path, name, is_dir=True, modified_at=None, size=0):
    return {
        "name": name,
        "path": path,
        "is_dir": is_dir,
        "size": size,
        "modified_at": modified_at,
        "mime_type": "application/octet-stream",
        "thumbnail": "",
    }


async def _seed_rename_fixture(factory):
    mtime = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    async with factory() as session:
        parent = Folder(
            id="parent", name="parent", path="/parent", parent_id=None,
            content_type="software", root_mapping_id=1, depth=0, status="active",
        )
        old_folder = Folder(
            id="old-folder", name="oldname", path="/parent/oldname", parent_id="parent",
            content_type="software", root_mapping_id=1, depth=1, status="active",
            modified_at=mtime,
        )
        desc_folder = Folder(
            id="desc-folder", name="sub", path="/parent/oldname/sub", parent_id="old-folder",
            content_type="software", root_mapping_id=1, depth=2, status="active",
            modified_at=mtime,
        )
        desc_resource = Resource(
            id="desc-resource", name="file.txt", path="/parent/oldname/sub/file.txt",
            parent_id="desc-folder", content_type="software", root_mapping_id=1,
            status="active", modified_at=mtime,
        )
        session.add_all([parent, old_folder, desc_folder, desc_resource])

        current_cycle = SyncCycle(
            id=1, cycle_type="normal", status="running",
            anchor_at=datetime(2026, 9, 6, tzinfo=timezone.utc),
            planned_folder_count=2, windows_total=4,
        )
        history_cycle = SyncCycle(
            id=2, cycle_type="normal", status="success",
            anchor_at=datetime(2026, 9, 5, tzinfo=timezone.utc),
            planned_folder_count=1, windows_total=4, windows_completed=4,
        )
        session.add_all([current_cycle, history_cycle])

        run = SyncRun(id=1, sync_type="rolling_window", status="running", roots_total=1)
        session.add(run)

        await session.flush()

        session.add(SyncCycleItem(
            cycle_id=1, folder_id="old-folder", folder_path="/parent/oldname",
            status="running", priority=100,
        ))
        session.add(SyncCycleItem(
            cycle_id=1, folder_id="desc-folder", folder_path="/parent/oldname/sub",
            status="pending", priority=100,
        ))
        session.add(SyncCycleItem(
            cycle_id=2, folder_id="old-folder", folder_path="/parent/oldname",
            status="success", priority=100,
        ))

        session.add(FolderScanState(folder_id="old-folder", path="/parent/oldname"))
        session.add(FolderScanState(folder_id="desc-folder", path="/parent/oldname/sub"))

        await session.execute(text(
            "INSERT INTO search_fts(object_id, object_type, name, extension, "
            "content_type, description, tags, breadcrumb_text) VALUES "
            "(\'old-folder\',\'folder\',\'oldname\',\'\',\'software\',\'\',\'\',\'/parent/oldname\'),"
            "(\'desc-folder\',\'folder\',\'sub\',\'\',\'software\',\'\',\'\',\'/parent/oldname/sub\'),"
            "(\'desc-resource\',\'resource\',\'file.txt\',\'txt\',\'software\',\'\',\'\',\'/parent/oldname/sub/file.txt\')"
        ))

        await session.commit()
    return mtime


async def test_rename_same_modified_at_preserves_folder_id_and_updates_paths(monkeypatch):
    """Same modified_at rename: Folder.id preserved, paths/queue/scan state/FTS updated, history unchanged, renamed=1."""
    state_engine, index_engine, _, index_factory = await _make_factories(monkeypatch)
    mtime = await _seed_rename_fixture(index_factory)

    async with index_factory() as session:
        parent = await session.get(Folder, "parent")
        cycle = await session.get(SyncCycle, 1)
        run = await session.get(SyncRun, 1)
        item = await session.scalar(select(SyncCycleItem).where(
            SyncCycleItem.cycle_id == 1, SyncCycleItem.folder_id == "old-folder"
        ))
        entries = [_entry("/parent/newname", "newname", is_dir=True, modified_at=mtime)]
        result = await rolling._commit_scope(session, cycle, item, run, parent, entries, "fp", enqueue_discovered=True)
        await session.commit()

        assert result["renamed"] == 1
        assert result["added"] == 0

    async with index_factory() as session:
        folder = await session.get(Folder, "old-folder")
        assert folder.name == "newname"
        assert folder.path == "/parent/newname"

        desc = await session.get(Folder, "desc-folder")
        assert desc.path == "/parent/newname/sub"

        res = await session.get(Resource, "desc-resource")
        assert res.path == "/parent/newname/sub/file.txt"

        cur_root_item = await session.scalar(select(SyncCycleItem).where(
            SyncCycleItem.cycle_id == 1, SyncCycleItem.folder_id == "old-folder"
        ))
        assert cur_root_item.folder_path == "/parent/newname"

        cur_desc_item = await session.scalar(select(SyncCycleItem).where(
            SyncCycleItem.cycle_id == 1, SyncCycleItem.folder_id == "desc-folder"
        ))
        assert cur_desc_item.folder_path == "/parent/newname/sub"

        hist_item = await session.scalar(select(SyncCycleItem).where(
            SyncCycleItem.cycle_id == 2, SyncCycleItem.folder_id == "old-folder"
        ))
        assert hist_item.folder_path == "/parent/oldname"

        root_state = await session.get(FolderScanState, "old-folder")
        assert root_state.path == "/parent/newname"
        desc_state = await session.get(FolderScanState, "desc-folder")
        assert desc_state.path == "/parent/newname/sub"

        fts_paths = [r[0] for r in (await session.execute(text(
            "SELECT breadcrumb_text FROM search_fts ORDER BY breadcrumb_text"
        ))).fetchall()]
        assert "/parent/newname" in fts_paths
        assert "/parent/newname/sub" in fts_paths
        assert "/parent/newname/sub/file.txt" in fts_paths
        assert not any("/parent/oldname" in p for p in fts_paths)

        changes = list((await session.scalars(select(SyncChange).where(
            SyncChange.change_type == "renamed"
        ))).all())
        assert len(changes) == 1

    await state_engine.dispose()
    await index_engine.dispose()


async def test_rename_different_modified_at_does_not_rename(monkeypatch):
    """Different modified_at: no rename, new + missing."""
    state_engine, index_engine, _, index_factory = await _make_factories(monkeypatch)
    mtime = await _seed_rename_fixture(index_factory)

    different_mtime = datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc)

    async with index_factory() as session:
        parent = await session.get(Folder, "parent")
        cycle = await session.get(SyncCycle, 1)
        run = await session.get(SyncRun, 1)
        item = await session.scalar(select(SyncCycleItem).where(
            SyncCycleItem.cycle_id == 1, SyncCycleItem.folder_id == "old-folder"
        ))
        entries = [_entry("/parent/newname", "newname", is_dir=True, modified_at=different_mtime)]
        result = await rolling._commit_scope(session, cycle, item, run, parent, entries, "fp", enqueue_discovered=True)
        await session.commit()

        assert result["renamed"] == 0
        assert result["added"] == 1

    async with index_factory() as session:
        folder = await session.get(Folder, "old-folder")
        assert folder.path == "/parent/oldname"

    await state_engine.dispose()
    await index_engine.dispose()


async def test_rename_sql_exception_rolls_back_all_changes(monkeypatch):
    """SQL exception during rename: rollback all Index records."""
    state_engine, index_engine, _, index_factory = await _make_factories(monkeypatch)
    mtime = await _seed_rename_fixture(index_factory)

    async with index_factory() as session:
        parent = await session.get(Folder, "parent")
        cycle = await session.get(SyncCycle, 1)
        run = await session.get(SyncRun, 1)
        item = await session.scalar(select(SyncCycleItem).where(
            SyncCycleItem.cycle_id == 1, SyncCycleItem.folder_id == "old-folder"
        ))

        original_execute = session.execute
        call_count = 0
        async def failing_execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 3:
                raise RuntimeError("simulated SQL failure during rename")
            return await original_execute(*args, **kwargs)

        monkeypatch.setattr(session, "execute", failing_execute)

        entries = [_entry("/parent/newname", "newname", is_dir=True, modified_at=mtime)]
        with pytest.raises(RuntimeError, match="simulated SQL failure"):
            await rolling._commit_scope(session, cycle, item, run, parent, entries, "fp", enqueue_discovered=True)
        await session.rollback()

    async with index_factory() as session:
        folder = await session.get(Folder, "old-folder")
        assert folder.path == "/parent/oldname"
        assert folder.name == "oldname"

        desc = await session.get(Folder, "desc-folder")
        assert desc.path == "/parent/oldname/sub"

    await state_engine.dispose()
    await index_engine.dispose()


async def test_rename_both_none_modified_at_does_not_rename(monkeypatch):
    """Both modified_at None: no rename (P0-1)."""
    state_engine, index_engine, _, index_factory = await _make_factories(monkeypatch)
    await _seed_rename_fixture(index_factory)

    async with index_factory() as session:
        old_folder = await session.get(Folder, "old-folder")
        old_folder.modified_at = None
        await session.commit()

    async with index_factory() as session:
        parent = await session.get(Folder, "parent")
        cycle = await session.get(SyncCycle, 1)
        run = await session.get(SyncRun, 1)
        item = await session.scalar(select(SyncCycleItem).where(
            SyncCycleItem.cycle_id == 1, SyncCycleItem.folder_id == "old-folder"
        ))
        entries = [_entry("/parent/newname", "newname", is_dir=True, modified_at=None)]
        result = await rolling._commit_scope(session, cycle, item, run, parent, entries, "fp", enqueue_discovered=True)
        await session.commit()
        assert result["renamed"] == 0
        assert result["added"] == 1

    await state_engine.dispose()
    await index_engine.dispose()


async def test_rename_only_old_none_modified_at_does_not_rename(monkeypatch):
    """Only old modified_at None: no rename (P0-1)."""
    state_engine, index_engine, _, index_factory = await _make_factories(monkeypatch)
    await _seed_rename_fixture(index_factory)

    async with index_factory() as session:
        old_folder = await session.get(Folder, "old-folder")
        old_folder.modified_at = None
        await session.commit()

    candidate_mtime = datetime(2026, 9, 3, 10, 0, tzinfo=timezone.utc)
    async with index_factory() as session:
        parent = await session.get(Folder, "parent")
        cycle = await session.get(SyncCycle, 1)
        run = await session.get(SyncRun, 1)
        item = await session.scalar(select(SyncCycleItem).where(
            SyncCycleItem.cycle_id == 1, SyncCycleItem.folder_id == "old-folder"
        ))
        entries = [_entry("/parent/newname", "newname", is_dir=True, modified_at=candidate_mtime)]
        result = await rolling._commit_scope(session, cycle, item, run, parent, entries, "fp", enqueue_discovered=True)
        await session.commit()
        assert result["renamed"] == 0
        assert result["added"] == 1

    await state_engine.dispose()
    await index_engine.dispose()


async def test_rename_only_candidate_none_modified_at_does_not_rename(monkeypatch):
    """Only candidate modified_at None: no rename (P0-1)."""
    state_engine, index_engine, _, index_factory = await _make_factories(monkeypatch)
    mtime = await _seed_rename_fixture(index_factory)

    async with index_factory() as session:
        parent = await session.get(Folder, "parent")
        cycle = await session.get(SyncCycle, 1)
        run = await session.get(SyncRun, 1)
        item = await session.scalar(select(SyncCycleItem).where(
            SyncCycleItem.cycle_id == 1, SyncCycleItem.folder_id == "old-folder"
        ))
        entries = [_entry("/parent/newname", "newname", is_dir=True, modified_at=None)]
        result = await rolling._commit_scope(session, cycle, item, run, parent, entries, "fp", enqueue_discovered=True)
        await session.commit()
        assert result["renamed"] == 0
        assert result["added"] == 1

    await state_engine.dispose()
    await index_engine.dispose()


async def test_rename_fts_failure_rolls_back_all_changes(monkeypatch):
    """FTS operation failure: caller rollback, all Index records preserved (P0-2b)."""
    state_engine, index_engine, _, index_factory = await _make_factories(monkeypatch)
    mtime = await _seed_rename_fixture(index_factory)

    async def failing_fts_delta(session, ops):
        return {"applied": 0, "failed": len(ops)}

    monkeypatch.setattr(rolling, "apply_search_fts_delta", failing_fts_delta)

    async with index_factory() as session:
        parent = await session.get(Folder, "parent")
        cycle = await session.get(SyncCycle, 1)
        run = await session.get(SyncRun, 1)
        item = await session.scalar(select(SyncCycleItem).where(
            SyncCycleItem.cycle_id == 1, SyncCycleItem.folder_id == "old-folder"
        ))
        entries = [_entry("/parent/newname", "newname", is_dir=True, modified_at=mtime)]
        with pytest.raises(RuntimeError, match="FTS delta apply failed"):
            await rolling._commit_scope(session, cycle, item, run, parent, entries, "fp", enqueue_discovered=True)
        await session.rollback()

    async with index_factory() as session:
        folder = await session.get(Folder, "old-folder")
        assert folder.path == "/parent/oldname"
        assert folder.name == "oldname"

        desc = await session.get(Folder, "desc-folder")
        assert desc.path == "/parent/oldname/sub"

        res = await session.get(Resource, "desc-resource")
        assert res.path == "/parent/oldname/sub/file.txt"

        cur_root_item = await session.scalar(select(SyncCycleItem).where(
            SyncCycleItem.cycle_id == 1, SyncCycleItem.folder_id == "old-folder"
        ))
        assert cur_root_item.folder_path == "/parent/oldname"

        root_state = await session.get(FolderScanState, "old-folder")
        assert root_state.path == "/parent/oldname"

        fts_paths = [r[0] for r in (await session.execute(text(
            "SELECT breadcrumb_text FROM search_fts ORDER BY breadcrumb_text"
        ))).fetchall()]
        assert "/parent/oldname" in fts_paths
        assert not any("/parent/newname" in p for p in fts_paths)

        rename_changes = list((await session.scalars(select(SyncChange).where(
            SyncChange.change_type == "renamed"
        ))).all())
        assert len(rename_changes) == 0

    await state_engine.dispose()
    await index_engine.dispose()


class _FakeAListClient:
    def __init__(self, entries):
        self._entries = entries

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def list_path(self, path, refresh=False, strict=False):
        return self._entries


async def test_scan_cycle_item_pure_rename_changed_true(monkeypatch):
    """Real _scan_cycle_item pure rename: changed is True, renamed == 1 (P1-2)."""
    state_engine, index_engine, _, index_factory = await _make_factories(monkeypatch)
    mtime = await _seed_rename_fixture(index_factory)

    # Add a cycle item for parent so _scan_cycle_item scans /parent listing
    async with index_factory() as session:
        session.add(SyncCycleItem(
            cycle_id=1, folder_id="parent", folder_path="/parent",
            status="pending", priority=100,
        ))
        await session.commit()

    raw_entries = [{"name": "newname", "is_dir": True, "size": 0, "modified": mtime.isoformat()}]
    client = _FakeAListClient(raw_entries)

    async with index_factory() as session:
        cycle = await session.get(SyncCycle, 1)
        run = await session.get(SyncRun, 1)
        item = await session.scalar(select(SyncCycleItem).where(
            SyncCycleItem.cycle_id == 1, SyncCycleItem.folder_id == "parent"
        ))
        result = await rolling._scan_cycle_item(session, client, cycle, item, run, force_refresh=False, enqueue_discovered=True)
        await session.commit()

        assert result["changed"] is True
        assert result["renamed"] == 1
        assert result["superseded"] is False

    async with index_factory() as session:
        folder = await session.get(Folder, "old-folder")
        assert folder.path == "/parent/newname"
        assert folder.name == "newname"

    await state_engine.dispose()
    await index_engine.dispose()
