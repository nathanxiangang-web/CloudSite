"""Focused tests for the parser candidate batch coordinator.

Covers:
- unchanged enqueue is idempotent; changed parser input creates a new candidate
- ordered candidate listing with status/resource_id filters and limit/offset
- bounded batch stops at max_items and at time_budget_seconds
- one failed item does not block later items
- restart recovery converts leftover running candidates to failed
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.database import IndexBase, StateBase
from cloudsite.models import Resource
from cloudsite.modules.automation.contracts.public import (
    INTERRUPTED_MESSAGE,
    enqueue_indexed_resource,
    list_parser_candidates,
    recover_interrupted_candidates,
    run_parser_candidate_batch,
)
from cloudsite.modules.automation.contracts.public import (
    ParserCandidateError,
    claim_parser_candidate,
    enqueue_parser_candidate,
    retry_parser_candidate,
)
from cloudsite.modules.automation.domain.resource_name_parser import PARSER_VERSION


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


def _resource(resource_id: str = "r1", name: str = "Tool-1.0.0-windows-x64.zip") -> Resource:
    return Resource(
        id=resource_id,
        name=name,
        path=f"/software/{name}",
        content_type="software",
        extension="zip",
        mime_type="application/zip",
        status="active",
    )


# ---------------------------------------------------------------------------
# 1. Unchanged and changed enqueue
# ---------------------------------------------------------------------------


async def test_enqueue_unchanged_is_idempotent_and_changed_creates_new(tmp_path):
    state_engine, index_engine, state_factory, index_factory = await _sessions(tmp_path)
    async with state_factory() as state, index_factory() as index:
        resource = _resource()
        index.add(resource)
        await index.flush()

        first, created_first = await enqueue_indexed_resource(state, index, resource.id)
        assert created_first is True
        assert first.status == "pending"
        assert first.parser_version == PARSER_VERSION

        second, created_second = await enqueue_indexed_resource(state, index, resource.id)
        assert created_second is False
        assert second.task_id == first.task_id

        resource.name = "Tool-2.0.0-linux-arm64.zip"
        resource.path = f"/software/{resource.name}"
        await index.flush()

        third, created_third = await enqueue_indexed_resource(state, index, resource.id)
        assert created_third is True
        assert third.task_id != first.task_id
        assert third.input_fingerprint != first.input_fingerprint
        assert third.resource_id == resource.id
    await state_engine.dispose()
    await index_engine.dispose()


async def test_enqueue_rejects_missing_or_inactive_resource(tmp_path):
    state_engine, index_engine, state_factory, index_factory = await _sessions(tmp_path)
    async with state_factory() as state, index_factory() as index:
        with pytest.raises(ParserCandidateError):
            await enqueue_indexed_resource(state, index, "r_missing")

        inactive = _resource(resource_id="r_inactive")
        inactive.status = "missing"
        index.add(inactive)
        await index.flush()
        with pytest.raises(ParserCandidateError):
            await enqueue_indexed_resource(state, index, inactive.id)
    await state_engine.dispose()
    await index_engine.dispose()


# ---------------------------------------------------------------------------
# 2. Ordered candidate listing with filters and bounds
# ---------------------------------------------------------------------------


async def test_list_orders_by_creation_and_applies_filters_and_bounds(tmp_path):
    state_engine, index_engine, state_factory, index_factory = await _sessions(tmp_path)
    async with state_factory() as state, index_factory() as index:
        r_a = _resource(resource_id="ra", name="A-1.0.0-windows-x64.zip")
        r_b = _resource(resource_id="rb", name="B-1.0.0-linux-arm64.zip")
        index.add_all([r_a, r_b])
        await index.flush()

        task_a, _ = await enqueue_indexed_resource(state, index, r_a.id)
        await state.flush()
        task_b, _ = await enqueue_indexed_resource(state, index, r_b.id)
        await state.flush()

        await claim_parser_candidate(state, task_a.task_id)
        await state.flush()

        ordered = await list_parser_candidates(state)
        assert [t.task_id for t in ordered] == [task_a.task_id, task_b.task_id]

        pending_only = await list_parser_candidates(state, status="pending")
        assert [t.task_id for t in pending_only] == [task_b.task_id]

        running_only = await list_parser_candidates(state, status="running")
        assert [t.task_id for t in running_only] == [task_a.task_id]

        filtered_by_resource = await list_parser_candidates(state, resource_id="rb")
        assert [t.task_id for t in filtered_by_resource] == [task_b.task_id]

        combined = await list_parser_candidates(
            state, status="pending", resource_id="rb"
        )
        assert [t.task_id for t in combined] == [task_b.task_id]

        empty = await list_parser_candidates(
            state, status="pending", resource_id="ra"
        )
        assert empty == []

        limited = await list_parser_candidates(state, limit=1)
        assert [t.task_id for t in limited] == [task_a.task_id]

        offset = await list_parser_candidates(state, limit=1, offset=1)
        assert [t.task_id for t in offset] == [task_b.task_id]

        beyond = await list_parser_candidates(state, limit=10, offset=5)
        assert beyond == []
    await state_engine.dispose()
    await index_engine.dispose()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"limit": 0}, "limit must be between"),
        ({"limit": 501}, "limit must be between"),
        ({"limit": True}, "limit must be between"),
        ({"offset": -1}, "offset must be"),
        ({"offset": False}, "offset must be"),
        ({"status": "unknown"}, "invalid parser candidate status"),
    ],
)
async def test_list_rejects_invalid_bounds_and_status(tmp_path, kwargs, message):
    state_engine, index_engine, state_factory, index_factory = await _sessions(tmp_path)
    async with state_factory() as state:
        with pytest.raises(ParserCandidateError, match=message):
            await list_parser_candidates(state, **kwargs)
    await state_engine.dispose()
    await index_engine.dispose()


# ---------------------------------------------------------------------------
# 3. Bounded batch: item and time bounds
# ---------------------------------------------------------------------------


async def _seed_pending(state, index, count: int, prefix: str = "r"):
    tasks = []
    for i in range(count):
        resource = _resource(
            resource_id=f"{prefix}{i}", name=f"Tool-{i}.0.0-windows-x64.zip"
        )
        index.add(resource)
        await index.flush()
        task, _ = await enqueue_indexed_resource(state, index, resource.id)
        await state.flush()
        tasks.append(task)
    return tasks


async def test_batch_stops_at_max_items(tmp_path):
    state_engine, index_engine, state_factory, index_factory = await _sessions(tmp_path)
    async with state_factory() as state, index_factory() as index:
        await _seed_pending(state, index, 5)

        result = await run_parser_candidate_batch(
            state, index, max_items=2, time_budget_seconds=30.0
        )

        assert result.attempted == 2
        assert result.stopped_reason == "max_items"
        assert all(o.task.status == "completed" for o in result.outcomes)

        remaining = await list_parser_candidates(state, status="pending")
        assert len(remaining) == 3
    await state_engine.dispose()
    await index_engine.dispose()


async def test_batch_stops_at_time_budget(tmp_path):
    state_engine, index_engine, state_factory, index_factory = await _sessions(tmp_path)
    async with state_factory() as state, index_factory() as index:
        await _seed_pending(state, index, 5)

        result = await run_parser_candidate_batch(
            state, index, max_items=100, time_budget_seconds=0.0
        )

        assert result.attempted == 0
        assert result.stopped_reason == "time_budget"
        assert result.outcomes == ()

        still_pending = await list_parser_candidates(state, status="pending")
        assert len(still_pending) == 5
    await state_engine.dispose()
    await index_engine.dispose()


async def test_batch_runs_all_when_budget_generous(tmp_path):
    state_engine, index_engine, state_factory, index_factory = await _sessions(tmp_path)
    async with state_factory() as state, index_factory() as index:
        await _seed_pending(state, index, 3)

        result = await run_parser_candidate_batch(
            state, index, max_items=100, time_budget_seconds=30.0
        )

        assert result.attempted == 3
        assert result.stopped_reason == "exhausted"
        assert all(o.task.status == "completed" for o in result.outcomes)
    await state_engine.dispose()
    await index_engine.dispose()


async def test_batch_respects_creation_order(tmp_path):
    state_engine, index_engine, state_factory, index_factory = await _sessions(tmp_path)
    async with state_factory() as state, index_factory() as index:
        tasks = await _seed_pending(state, index, 3)

        result = await run_parser_candidate_batch(
            state, index, max_items=3, time_budget_seconds=30.0
        )

        executed_ids = [o.task.task_id for o in result.outcomes]
        assert executed_ids == [t.task_id for t in tasks]
    await state_engine.dispose()
    await index_engine.dispose()


# ---------------------------------------------------------------------------
# 4. One failed item does not block later items
# ---------------------------------------------------------------------------


async def test_batch_continues_past_failed_item(tmp_path):
    state_engine, index_engine, state_factory, index_factory = await _sessions(tmp_path)
    async with state_factory() as state, index_factory() as index:
        good_a = _resource(resource_id="good_a", name="A-1.0.0-windows-x64.zip")
        good_b = _resource(resource_id="good_b", name="B-2.0.0-linux-arm64.zip")
        index.add_all([good_a, good_b])
        await index.flush()

        task_a, _ = await enqueue_indexed_resource(state, index, good_a.id)
        await state.flush()
        task_b, _ = await enqueue_indexed_resource(state, index, good_b.id)
        await state.flush()

        stale, _ = await enqueue_parser_candidate(
            state,
            resource_id="good_a",
            input_fingerprint="0" * 64,
            parser_version=PARSER_VERSION,
        )
        await state.flush()

        good_a.name = "A-1.0.0-windows-x64.zip"
        await index.flush()

        result = await run_parser_candidate_batch(
            state, index, max_items=100, time_budget_seconds=30.0
        )

        assert result.attempted == 3
        assert result.stopped_reason == "exhausted"

        by_task = {o.task.task_id: o for o in result.outcomes}
        assert by_task[task_a.task_id].task.status == "completed"
        assert by_task[task_b.task_id].task.status == "completed"
        assert by_task[stale.task_id].task.status == "failed"
        assert by_task[stale.task_id].error is not None
    await state_engine.dispose()
    await index_engine.dispose()


# ---------------------------------------------------------------------------
# 5. Restart recovery
# ---------------------------------------------------------------------------


async def test_recover_interrupted_candidates(tmp_path):
    state_engine, index_engine, state_factory, index_factory = await _sessions(tmp_path)
    async with state_factory() as state, index_factory() as index:
        r1 = _resource(resource_id="rc1", name="C-1.0.0-windows-x64.zip")
        r2 = _resource(resource_id="rc2", name="D-2.0.0-linux-arm64.zip")
        index.add_all([r1, r2])
        await index.flush()

        task1, _ = await enqueue_indexed_resource(state, index, r1.id)
        task2, _ = await enqueue_indexed_resource(state, index, r2.id)
        await state.flush()

        await claim_parser_candidate(state, task1.task_id)
        await claim_parser_candidate(state, task2.task_id)
        await state.flush()

        running_before = await list_parser_candidates(state, status="running")
        assert len(running_before) == 2

        recovered = await recover_interrupted_candidates(state)

        assert len(recovered) == 2
        assert all(r.status == "failed" for r in recovered)
        assert all(r.error_text == INTERRUPTED_MESSAGE for r in recovered)

        running_after = await list_parser_candidates(state, status="running")
        assert running_after == []

        failed_after = await list_parser_candidates(state, status="failed")
        assert len(failed_after) == 2

        retried = await retry_parser_candidate(state, task1.task_id, max_retries=3)
        assert retried.status == "pending"
        assert retried.retry_count == 1
    await state_engine.dispose()
    await index_engine.dispose()


async def test_recover_interrupted_candidates_no_running_is_noop(tmp_path):
    state_engine, index_engine, state_factory, index_factory = await _sessions(tmp_path)
    async with state_factory() as state, index_factory() as index:
        recovered = await recover_interrupted_candidates(state)
        assert recovered == []
    await state_engine.dispose()
    await index_engine.dispose()
