"""A4 content quality service tests.

 Covers: detection generates todos, deduplication (no duplicate open items),
 four-state computation, dismiss/resolve state transitions, budget control,
 user feedback creates linked todo, review feedback updates todo,
 search query logging and no-result aggregation.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from cloudsite.database import IndexBase, StateBase
from cloudsite.models import (
    CatalogAsset,
    CatalogEntry,
    CatalogLocation,
    CatalogRelease,
    ContentFeedback,
    QualityTodo,
    Resource,
    SearchQueryLog,
)
from cloudsite.services import quality


@pytest.fixture
async def sessions(tmp_path):
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)
    StateSession = async_sessionmaker(state_engine, expire_on_commit=False, class_=AsyncSession)
    IndexSession = async_sessionmaker(index_engine, expire_on_commit=False, class_=AsyncSession)
    yield StateSession, IndexSession
    await state_engine.dispose()
    await index_engine.dispose()


def _make_entry(entry_id="ce_testentry00000000000000001", **kw):
    defaults = {
        "entry_id": entry_id,
        "content_type": "software",
        "slug": "test-entry",
        "title": "Test Entry",
        "summary": "",
        "description": "",
        "status": "published",
        "revision": 1,
    }
    defaults.update(kw)
    return CatalogEntry(**defaults)


def _make_release(release_id="cr_testrelease0000000000000001", entry_id="ce_testentry00000000000000001", **kw):
    from datetime import datetime, timedelta, timezone
    old_date = datetime.now(timezone.utc) - timedelta(days=365)
    defaults = {
        "release_id": release_id,
        "entry_id": entry_id,
        "slug": "v1.0",
        "title": "v1.0",
        "release_notes": "",
        "status": "published",
        "sort_order": 0,
        "channel": "stable",
        "release_date": old_date,
        "is_recommended": False,
    }
    defaults.update(kw)
    return CatalogRelease(**defaults)


def _make_asset(asset_id="cr_testasset00000000000000001", release_id="cr_testrelease0000000000000001", **kw):
    defaults = {
        "asset_id": asset_id,
        "release_id": release_id,
        "slug": "windows-x64",
        "display_name": "Windows x64",
        "platform": "windows",
        "kind": "installer",
        "architecture": "x64",
        "package_type": "msi",
        "language": "unknown",
        "build_label": "",
        "checksum": "",
        "checksum_algorithm": "",
        "size": 0,
        "status": "active",
        "sort_order": 0,
    }
    defaults.update(kw)
    return CatalogAsset(**defaults)


def _make_location(location_id="cl_testloc00000000000000000001", asset_id="cr_testasset00000000000000001", **kw):
    defaults = {
        "location_id": location_id,
        "asset_id": asset_id,
        "resource_id": "r_testresource0000000000000001",
        "root_mapping_id": None,
        "label": "",
        "is_primary": True,
        "status": "active",
    }
    defaults.update(kw)
    return CatalogLocation(**defaults)


def _make_resource(rid="r_testresource0000000000000001", **kw):
    defaults = {
        "id": rid,
        "name": "test.zip",
        "path": "/test/test.zip",
        "parent_id": None,
        "content_type": "software",
        "root_mapping_id": None,
        "extension": "zip",
        "mime_type": "application/zip",
        "size": 100,
    }
    defaults.update(kw)
    return Resource(**defaults)


# ---- detection tests ----

async def test_detect_missing_descriptions(sessions):
    StateSession, _ = sessions
    async with StateSession() as state:
        state.add(_make_entry(summary="", description=""))
        state.add(_make_entry(entry_id="ce_testentry00000000000000002", slug="entry-2", summary="has summary", description=""))
        await state.commit()

    async with StateSession() as state:
        found, dedup = await quality.detect_missing_descriptions(state, run_id="dr_test")
        await state.commit()
        assert found == 1
        assert dedup == 0

    async with StateSession() as state:
        found, dedup = await quality.detect_missing_descriptions(state, run_id="dr_test2")
        await state.commit()
        assert found == 0
        assert dedup == 1


async def test_detect_stale_locations(sessions):
    StateSession, IndexSession = sessions
    async with StateSession() as state:
        state.add(_make_entry())
        state.add(_make_release())
        state.add(_make_asset())
        state.add(_make_location())
        await state.commit()

    async with StateSession() as state, IndexSession() as index:
        found, dedup = await quality.detect_stale_locations(state, index, run_id="dr_test")
        await state.commit()
        assert found == 1
        assert dedup == 0

    async with StateSession() as state:
        todos = (await state.scalars(select(QualityTodo))).all()
        assert len(todos) == 1
        detail = quality._decode_detail(todos[0].detail_json)
        assert detail["file_exists"] is False
        assert detail["download_ready"] is False


async def test_detect_stale_locations_with_active_resource(sessions):
    StateSession, IndexSession = sessions
    async with IndexSession() as index:
        index.add(_make_resource())
        await index.commit()
    async with StateSession() as state:
        state.add(_make_entry())
        state.add(_make_release())
        state.add(_make_asset())
        state.add(_make_location())
        await state.commit()

    async with StateSession() as state, IndexSession() as index:
        found, _ = await quality.detect_stale_locations(state, index, run_id="dr_test")
        await state.commit()
        assert found == 0


async def test_detect_old_versions(sessions):
    StateSession, _ = sessions
    async with StateSession() as state:
        state.add(_make_entry())
        state.add(_make_release())
        await state.commit()

    async with StateSession() as state:
        found, dedup = await quality.detect_old_versions_for_review(state, run_id="dr_test", age_days=180)
        await state.commit()
        assert found == 1
        assert dedup == 0


async def test_detect_suspected_duplicates(sessions):
    StateSession, _ = sessions
    async with StateSession() as state:
        state.add(_make_entry(entry_id="ce_aaaaaaaaaaaaaaaaaaaaaaaa01", slug="a", title="Same Title"))
        state.add(_make_entry(entry_id="ce_aaaaaaaaaaaaaaaaaaaaaaaa02", slug="b", title="Same Title"))
        await state.commit()

    async with StateSession() as state:
        found, _ = await quality.detect_suspected_duplicates(state, run_id="dr_test")
        await state.commit()
        assert found == 2


async def test_detect_no_result_queries(sessions):
    StateSession, _ = sessions
    async with StateSession() as state:
        for _ in range(5):
            state.add(SearchQueryLog(query="missing tool", result_count=0))
        state.add(SearchQueryLog(query="found tool", result_count=3))
        await state.commit()

    async with StateSession() as state:
        found, _ = await quality.detect_no_result_queries(state, run_id="dr_test", threshold=3)
        await state.commit()
        assert found == 1


async def test_run_quality_detection(sessions):
    StateSession, IndexSession = sessions
    async with StateSession() as state:
        state.add(_make_entry())
        state.add(_make_release())
        await state.commit()

    async with StateSession() as state, IndexSession() as index:
        result = await quality.run_quality_detection(state, index, budget_ms=10000)
        await state.commit()
        assert result.status == "completed"
        assert result.items_found >= 1
        assert result.actual_ms >= 0
        assert "missing_description" in result.breakdown


async def test_list_detection_runs_returns_persistence_neutral_records(
    sessions,
):
    StateSession, IndexSession = sessions
    async with StateSession() as state, IndexSession() as index:
        result = await quality.run_quality_detection(
            state,
            index,
            budget_ms=10000,
        )
        await state.commit()

    async with StateSession() as state:
        rows, total = await quality.list_detection_runs(
            state,
            page=1,
            page_size=20,
        )
        assert total == 1
        assert len(rows) == 1
        assert rows[0].run_id == result.run_id
        assert rows[0].status == "completed"
        assert isinstance(rows[0].breakdown, dict)


async def test_run_quality_detection_budget_timeout(sessions):
    StateSession, IndexSession = sessions
    async with StateSession() as state, IndexSession() as index:
        result = await quality.run_quality_detection(state, index, budget_ms=1)
        await state.commit()
        assert result.status in ("completed", "timeout")


# ---- deduplication tests ----

async def test_dedup_no_duplicate_open_todos(sessions):
    StateSession, _ = sessions
    async with StateSession() as state:
        state.add(_make_entry())
        await state.commit()

    async with StateSession() as state:
        await quality.detect_missing_descriptions(state, run_id="dr_1")
        await state.commit()
    async with StateSession() as state:
        await quality.detect_missing_descriptions(state, run_id="dr_2")
        await state.commit()

    async with StateSession() as state:
        todos = (await state.scalars(
            select(QualityTodo).where(QualityTodo.status == "open")
        )).all()
        assert len(todos) == 1


async def test_recreate_after_dismiss(sessions):
    StateSession, _ = sessions
    async with StateSession() as state:
        state.add(_make_entry())
        await state.commit()

    async with StateSession() as state:
        await quality.detect_missing_descriptions(state, run_id="dr_1")
        await state.commit()

    async with StateSession() as state:
        todos = (await state.scalars(select(QualityTodo))).all()
        todo_id = todos[0].todo_id
        await quality.dismiss_quality_todo(state, todo_id, reason="false positive")
        await state.commit()

    async with StateSession() as state:
        found, _ = await quality.detect_missing_descriptions(state, run_id="dr_2")
        await state.commit()
        assert found == 1

    async with StateSession() as state:
        open_todos = (await state.scalars(
            select(QualityTodo).where(QualityTodo.status == "open")
        )).all()
        assert len(open_todos) == 1


# ---- state transition tests ----

async def test_dismiss_todo(sessions):
    StateSession, _ = sessions
    async with StateSession() as state:
        state.add(_make_entry())
        await state.commit()
    async with StateSession() as state:
        await quality.detect_missing_descriptions(state, run_id="dr_1")
        await state.commit()
    async with StateSession() as state:
        todos = (await state.scalars(select(QualityTodo))).all()
        todo_id = todos[0].todo_id
        summary = await quality.dismiss_quality_todo(state, todo_id, reason="not an issue")
        await state.commit()
        assert summary.status == "dismissed"
        assert summary.dismiss_reason == "not an issue"

    async with StateSession() as state:
        with pytest.raises(quality.QualityTodoStateInvalid):
            todo = (await state.scalars(select(QualityTodo))).first()
            await quality.dismiss_quality_todo(state, todo.todo_id)


async def test_resolve_todo(sessions):
    StateSession, _ = sessions
    async with StateSession() as state:
        state.add(_make_entry())
        await state.commit()
    async with StateSession() as state:
        await quality.detect_missing_descriptions(state, run_id="dr_1")
        await state.commit()
    async with StateSession() as state:
        todos = (await state.scalars(select(QualityTodo))).all()
        todo_id = todos[0].todo_id
        summary = await quality.resolve_quality_todo(state, todo_id)
        await state.commit()
        assert summary.status == "resolved"


async def test_batch_dismiss(sessions):
    StateSession, _ = sessions
    async with StateSession() as state:
        state.add(_make_entry(entry_id="ce_aaaaaaaaaaaaaaaaaaaaaaaa01", slug="a"))
        state.add(_make_entry(entry_id="ce_aaaaaaaaaaaaaaaaaaaaaaaa02", slug="b"))
        await state.commit()
    async with StateSession() as state:
        await quality.detect_missing_descriptions(state, run_id="dr_1")
        await state.commit()
    async with StateSession() as state:
        todos = (await state.scalars(select(QualityTodo))).all()
        ids = [t.todo_id for t in todos]
        result = await quality.batch_dismiss_quality_todos(state, ids, reason="batch")
        await state.commit()
        assert result.succeeded == 2
        assert result.failed == 0


async def test_batch_dismiss_partial_failure(sessions):
    StateSession, _ = sessions
    async with StateSession() as state:
        state.add(_make_entry())
        await state.commit()
    async with StateSession() as state:
        await quality.detect_missing_descriptions(state, run_id="dr_1")
        await state.commit()
    async with StateSession() as state:
        todos = (await state.scalars(select(QualityTodo))).all()
        real_id = todos[0].todo_id
        result = await quality.batch_dismiss_quality_todos(state, [real_id, "ct_nonexistent00000000000000000000"])
        await state.commit()
        assert result.succeeded == 1
        assert result.failed == 1


# ---- feedback tests ----

async def test_create_feedback_creates_todo(sessions):
    StateSession, _ = sessions
    async with StateSession() as state:
        summary = await quality.create_content_feedback(
            state,
            user_id=1,
            target_type="entry",
            target_id="ce_testentry00000000000000001",
            feedback_kind="missing_content",
            description="This entry has no description",
        )
        await state.commit()
        assert summary.status == "pending"
        assert summary.todo_id is not None

    async with StateSession() as state:
        todo = await state.scalar(select(QualityTodo).where(QualityTodo.todo_id == summary.todo_id))
        assert todo is not None
        assert todo.source == "user_feedback"
        assert todo.status == "open"


async def test_review_feedback_updates_todo(sessions):
    StateSession, _ = sessions
    async with StateSession() as state:
        fb = await quality.create_content_feedback(
            state,
            user_id=1,
            target_type="entry",
            target_id="ce_testentry00000000000000001",
            feedback_kind="broken_link",
            description="Download link is broken",
        )
        await state.commit()
        feedback_id = fb.feedback_id
        todo_id = fb.todo_id

    async with StateSession() as state:
        result = await quality.review_content_feedback(
            state, feedback_id, admin_note="fixed", new_status="resolved",
        )
        await state.commit()
        assert result.status == "resolved"

    async with StateSession() as state:
        todo = await state.scalar(select(QualityTodo).where(QualityTodo.todo_id == todo_id))
        assert todo.status == "resolved"


async def test_review_feedback_invalid_state(sessions):
    StateSession, _ = sessions
    async with StateSession() as state:
        fb = await quality.create_content_feedback(
            state,
            user_id=1,
            target_type="entry",
            target_id="ce_testentry00000000000000001",
            feedback_kind="other",
            description="test",
        )
        await state.commit()
        feedback_id = fb.feedback_id

    async with StateSession() as state:
        await quality.review_content_feedback(state, feedback_id, new_status="reviewed")
        await state.commit()

    async with StateSession() as state:
        with pytest.raises(quality.QualityTodoStateInvalid):
            await quality.review_content_feedback(state, feedback_id, new_status="resolved")


# ---- search query logging ----

async def test_log_search_query(sessions):
    StateSession, _ = sessions
    async with StateSession() as state:
        await quality.log_search_query(state, query="test query", result_count=5, user_id=1)
        await state.commit()
    async with StateSession() as state:
        logs = (await state.scalars(select(SearchQueryLog))).all()
        assert len(logs) == 1
        assert logs[0].query == "test query"
        assert logs[0].result_count == 5


async def test_no_result_aggregation_threshold(sessions):
    StateSession, _ = sessions
    async with StateSession() as state:
        for _ in range(2):
            state.add(SearchQueryLog(query="rare", result_count=0))
        await state.commit()
    async with StateSession() as state:
        found, _ = await quality.detect_no_result_queries(state, run_id="dr_1", threshold=3)
        await state.commit()
        assert found == 0


# ---- list tests ----

async def test_list_quality_todos_filters(sessions):
    StateSession, _ = sessions
    async with StateSession() as state:
        state.add(_make_entry())
        await state.commit()
    async with StateSession() as state:
        await quality.detect_missing_descriptions(state, run_id="dr_1")
        await state.commit()
    async with StateSession() as state:
        items, total = await quality.list_quality_todos(state, todo_type="missing_description", status="open")
        assert total == 1
        assert items[0].todo_type == "missing_description"
    async with StateSession() as state:
        items, total = await quality.list_quality_todos(state, status="dismissed")
        assert total == 0


async def test_get_quality_todo_not_found(sessions):
    StateSession, _ = sessions
    async with StateSession() as state:
        with pytest.raises(quality.QualityTodoNotFound):
            await quality.get_quality_todo(state, "ct_nonexistent00000000000000000000")