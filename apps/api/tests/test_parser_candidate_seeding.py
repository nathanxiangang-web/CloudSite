"""Focused tests for seeding parser candidates from sync changes.

Covers:
- added/updated resources create candidates
- unchanged repeat is idempotent (existing count, no duplication)
- changed parser input creates a new candidate
- removed/folder/inactive/missing rows are skipped with explicit counts
- per-item failure continuation (error count, later changes still processed)
- bounds: max_items stops the batch
- continuation cursor: after_change_id resumes from last_change_id
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.database import IndexBase, StateBase
from cloudsite.models import Resource, SyncChange, SyncRun
from cloudsite.modules.automation.contracts.public import enqueue_indexed_resource
from cloudsite.modules.automation.contracts.public import ParserCandidateError
from cloudsite.modules.automation.contracts.public import (
    seed_parser_candidates_from_sync_run,
)
from cloudsite.services.resource_name_parser import PARSER_VERSION
from cloudsite.modules.automation.application import parser_candidate_seeding as parser_candidate_seeding_impl


async def _sessions(tmp_path):
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)
    return (
        state_engine,
        index_engine,
        async_sessionmaker(state_engine, expire_on_commit=False),
        async_sessionmaker(index_engine, expire_on_commit=False),
    )


def _resource(resource_id: str, name: str = "Tool-1.0.0-windows-x64.zip") -> Resource:
    return Resource(
        id=resource_id,
        name=name,
        path=f"/software/{name}",
        content_type="software",
        extension="zip",
        mime_type="application/zip",
        status="active",
    )


async def _make_run(index, *, status: str = "success") -> SyncRun:
    run = SyncRun(sync_type="rolling_window", status=status)
    index.add(run)
    await index.flush()
    return run


async def _add_change(
    index,
    run_id: int,
    *,
    object_type: str = "resource",
    object_id: str = "r1",
    change_type: str = "added",
) -> SyncChange:
    change = SyncChange(
        sync_run_id=run_id,
        object_type=object_type,
        object_id=object_id,
        change_type=change_type,
    )
    index.add(change)
    await index.flush()
    return change


# ---------------------------------------------------------------------------
# 1. Added/updated resources create candidates
# ---------------------------------------------------------------------------


async def test_added_and_updated_resources_create_candidates(tmp_path):
    state_engine, index_engine, state_factory, index_factory = await _sessions(tmp_path)
    async with state_factory() as state, index_factory() as index:
        run = await _make_run(index)
        r1 = _resource("r1", "A-1.0.0-windows-x64.zip")
        r2 = _resource("r2", "B-2.0.0-linux-arm64.zip")
        index.add_all([r1, r2])
        await index.flush()
        await _add_change(index, run.id, object_id="r1", change_type="added")
        await _add_change(index, run.id, object_id="r2", change_type="updated")

        result = await seed_parser_candidates_from_sync_run(
            state, index, sync_run_id=run.id, max_items=10
        )

        assert result.created == 2
        assert result.existing == 0
        assert result.skipped == 0
        assert result.error == 0
        assert result.stopped_reason == "exhausted"
        assert result.last_change_id > 0
    await state_engine.dispose()
    await index_engine.dispose()


# ---------------------------------------------------------------------------
# 2. Unchanged repeat is idempotent
# ---------------------------------------------------------------------------


async def test_unchanged_repeat_is_idempotent(tmp_path):
    state_engine, index_engine, state_factory, index_factory = await _sessions(tmp_path)
    async with state_factory() as state, index_factory() as index:
        run = await _make_run(index)
        r1 = _resource("r1", "A-1.0.0-windows-x64.zip")
        index.add(r1)
        await index.flush()
        await _add_change(index, run.id, object_id="r1", change_type="added")

        first = await seed_parser_candidates_from_sync_run(
            state, index, sync_run_id=run.id, max_items=10
        )
        assert first.created == 1

        second = await seed_parser_candidates_from_sync_run(
            state, index, sync_run_id=run.id, max_items=10
        )
        assert second.created == 0
        assert second.existing == 1
        assert second.error == 0
    await state_engine.dispose()
    await index_engine.dispose()


# ---------------------------------------------------------------------------
# 3. Changed parser input creates a new candidate
# ---------------------------------------------------------------------------


async def test_changed_parser_input_creates_new_candidate(tmp_path):
    state_engine, index_engine, state_factory, index_factory = await _sessions(tmp_path)
    async with state_factory() as state, index_factory() as index:
        run = await _make_run(index)
        r1 = _resource("r1", "A-1.0.0-windows-x64.zip")
        index.add(r1)
        await index.flush()
        await _add_change(index, run.id, object_id="r1", change_type="added")

        first = await seed_parser_candidates_from_sync_run(
            state, index, sync_run_id=run.id, max_items=10
        )
        assert first.created == 1
        first_task, _ = await enqueue_indexed_resource(state, index, "r1")

        r1.name = "A-2.0.0-linux-arm64.zip"
        r1.path = f"/software/{r1.name}"
        await index.flush()

        second = await seed_parser_candidates_from_sync_run(
            state, index, sync_run_id=run.id, max_items=10
        )
        assert second.created == 1
        assert second.existing == 0

        second_task, _ = await enqueue_indexed_resource(state, index, "r1")
        assert second_task.task_id != first_task.task_id
        assert second_task.input_fingerprint != first_task.input_fingerprint
    await state_engine.dispose()
    await index_engine.dispose()


# ---------------------------------------------------------------------------
# 4. Removed/folder/inactive/missing rows are skipped
# ---------------------------------------------------------------------------


async def test_removed_folder_inactive_and_missing_are_skipped(tmp_path):
    state_engine, index_engine, state_factory, index_factory = await _sessions(tmp_path)
    async with state_factory() as state, index_factory() as index:
        run = await _make_run(index)
        active = _resource("r_active", "A-1.0.0-windows-x64.zip")
        inactive = _resource("r_inactive", "B-2.0.0-linux-arm64.zip")
        inactive.status = "missing"
        index.add_all([active, inactive])
        await index.flush()

        await _add_change(index, run.id, object_id="r_active", change_type="added")
        await _add_change(index, run.id, object_id="r_removed", change_type="removed")
        await _add_change(index, run.id, object_type="folder", object_id="f1", change_type="added")
        await _add_change(index, run.id, object_id="r_inactive", change_type="updated")
        await _add_change(index, run.id, object_id="r_missing", change_type="added")

        result = await seed_parser_candidates_from_sync_run(
            state, index, sync_run_id=run.id, max_items=10
        )

        assert result.created == 1
        assert result.skipped == 4
        assert result.error == 0
        assert result.stopped_reason == "exhausted"
    await state_engine.dispose()
    await index_engine.dispose()


# ---------------------------------------------------------------------------
# 5. Per-item failure continuation
# ---------------------------------------------------------------------------


async def test_per_item_failure_continues(tmp_path, monkeypatch):
    state_engine, index_engine, state_factory, index_factory = await _sessions(tmp_path)
    async with state_factory() as state, index_factory() as index:
        run = await _make_run(index)
        r1 = _resource("r1", "A-1.0.0-windows-x64.zip")
        r2 = _resource("r2", "B-2.0.0-linux-arm64.zip")
        r3 = _resource("r3", "C-3.0.0-macos-arm64.zip")
        index.add_all([r1, r2, r3])
        await index.flush()

        await _add_change(index, run.id, object_id="r1", change_type="added")
        bad_change = await _add_change(index, run.id, object_id="r2", change_type="added")
        await _add_change(index, run.id, object_id="r3", change_type="updated")

        original_enqueue = parser_candidate_seeding_impl.enqueue_indexed_resource

        async def flaky_enqueue(state, index, resource_id):
            if resource_id == "r2":
                raise RuntimeError("simulated enqueue failure")
            return await original_enqueue(state, index, resource_id)

        monkeypatch.setattr(parser_candidate_seeding_impl, "enqueue_indexed_resource", flaky_enqueue)

        result = await seed_parser_candidates_from_sync_run(
            state, index, sync_run_id=run.id, max_items=10
        )

        assert result.created == 2
        assert result.error == 1
        assert result.skipped == 0
        assert result.last_change_id > bad_change.id
    await state_engine.dispose()
    await index_engine.dispose()


# ---------------------------------------------------------------------------
# 6. Bounds: max_items stops the batch
# ---------------------------------------------------------------------------


async def test_max_items_bounds_processed_rows(tmp_path):
    state_engine, index_engine, state_factory, index_factory = await _sessions(tmp_path)
    async with state_factory() as state, index_factory() as index:
        run = await _make_run(index)
        for i in range(5):
            r = _resource(f"r{i}", f"Tool-{i}.0.0-windows-x64.zip")
            index.add(r)
            await index.flush()
            await _add_change(index, run.id, object_id=f"r{i}", change_type="added")

        result = await seed_parser_candidates_from_sync_run(
            state, index, sync_run_id=run.id, max_items=3
        )

        assert result.created == 3
        assert result.stopped_reason == "max_items"
    await state_engine.dispose()
    await index_engine.dispose()


async def test_invalid_bounds_fail_closed(tmp_path):
    state_engine, index_engine, state_factory, index_factory = await _sessions(tmp_path)
    async with state_factory() as state, index_factory() as index:
        run = await _make_run(index)
        r1 = _resource("r1")
        index.add(r1)
        await index.flush()
        await _add_change(index, run.id, object_id="r1", change_type="added")

        for kwargs in (
            {"sync_run_id": run.id, "max_items": 0},
            {"sync_run_id": run.id, "max_items": 501},
            {"sync_run_id": run.id, "max_items": True},
            {"sync_run_id": run.id, "max_items": 10, "after_change_id": -1},
        ):
            with pytest.raises(ParserCandidateError):
                await seed_parser_candidates_from_sync_run(state, index, **kwargs)
    await state_engine.dispose()
    await index_engine.dispose()


# ---------------------------------------------------------------------------
# 7. Continuation cursor
# ---------------------------------------------------------------------------


async def test_continuation_cursor_resumes(tmp_path):
    state_engine, index_engine, state_factory, index_factory = await _sessions(tmp_path)
    async with state_factory() as state, index_factory() as index:
        run = await _make_run(index)
        change_ids = []
        for i in range(4):
            r = _resource(f"r{i}", f"Tool-{i}.0.0-windows-x64.zip")
            index.add(r)
            await index.flush()
            c = await _add_change(index, run.id, object_id=f"r{i}", change_type="added")
            change_ids.append(c.id)

        first = await seed_parser_candidates_from_sync_run(
            state, index, sync_run_id=run.id, max_items=2
        )
        assert first.created == 2
        assert first.last_change_id == change_ids[1]
        assert first.stopped_reason == "max_items"

        second = await seed_parser_candidates_from_sync_run(
            state, index,
            sync_run_id=run.id,
            max_items=2,
            after_change_id=first.last_change_id,
        )
        assert second.created == 2
        assert second.existing == 0
        assert second.last_change_id == change_ids[3]
        assert second.stopped_reason == "exhausted"

        third = await seed_parser_candidates_from_sync_run(
            state, index,
            sync_run_id=run.id,
            max_items=2,
            after_change_id=second.last_change_id,
        )
        assert third.created == 0
        assert third.last_change_id == second.last_change_id
        assert third.stopped_reason == "exhausted"
    await state_engine.dispose()
    await index_engine.dispose()


# ---------------------------------------------------------------------------
# 8. Empty or nonexistent sync run
# ---------------------------------------------------------------------------


async def test_nonexistent_or_unfinished_sync_run_is_rejected(tmp_path):
    state_engine, index_engine, state_factory, index_factory = await _sessions(tmp_path)
    async with state_factory() as state, index_factory() as index:
        with pytest.raises(ParserCandidateError, match="not found"):
            await seed_parser_candidates_from_sync_run(
                state, index, sync_run_id=999, max_items=10
            )
        unfinished = await _make_run(index, status="running")
        with pytest.raises(ParserCandidateError, match="not completed"):
            await seed_parser_candidates_from_sync_run(
                state, index, sync_run_id=unfinished.id, max_items=10
            )
    await state_engine.dispose()
    await index_engine.dispose()


# ---------------------------------------------------------------------------
# 9. Parser version matches current parser
# ---------------------------------------------------------------------------


async def test_seeded_candidates_use_current_parser_version(tmp_path):
    state_engine, index_engine, state_factory, index_factory = await _sessions(tmp_path)
    async with state_factory() as state, index_factory() as index:
        run = await _make_run(index)
        r1 = _resource("r1")
        index.add(r1)
        await index.flush()
        await _add_change(index, run.id, object_id="r1", change_type="added")

        await seed_parser_candidates_from_sync_run(
            state, index, sync_run_id=run.id, max_items=10
        )

        task, _ = await enqueue_indexed_resource(state, index, "r1")
        assert task.parser_version == PARSER_VERSION
    await state_engine.dispose()
    await index_engine.dispose()
