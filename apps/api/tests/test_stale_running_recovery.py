"""Stale running v2_sync_progress recovery regression tests.

When the process restarts while v2_sync_progress.status == "running", the dead
worker can never complete the run, so every sync path treats it as forever-active
and blocks scheduling. recover_interrupted_v2_sync must fold such rows to
"failed" with an explicit error_message and leave terminal/absent states alone.
"""

import json

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.models import SystemSetting
from cloudsite.modules.indexing.infrastructure.status_store import (
    read_v2_sync_progress,
    recover_interrupted_v2_sync,
)
from cloudsite.platform.db import StateBase


async def _make_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)
    return engine, factory


async def test_stale_running_recovered_on_startup():
    engine, factory = await _make_factory()
    try:
        async with factory() as session:
            session.add(
                SystemSetting(
                    key="v2_sync_progress",
                    value=json.dumps(
                        {"status": "running", "categories_done": 2}
                    ),
                    value_type="string",
                )
            )
            await session.commit()

        async with factory() as session:
            recovered = await recover_interrupted_v2_sync(session)
            assert recovered is True

        async with factory() as session:
            progress = await read_v2_sync_progress(session)
            assert progress["status"] == "failed"
            assert progress["error_message"] == "interrupted by process restart"
            assert progress["categories_done"] == 2
    finally:
        await engine.dispose()


async def test_completed_not_affected():
    engine, factory = await _make_factory()
    try:
        async with factory() as session:
            session.add(
                SystemSetting(
                    key="v2_sync_progress",
                    value=json.dumps({"status": "completed"}),
                    value_type="string",
                )
            )
            await session.commit()

        async with factory() as session:
            recovered = await recover_interrupted_v2_sync(session)
            assert recovered is False

        async with factory() as session:
            progress = await read_v2_sync_progress(session)
            assert progress["status"] == "completed"
            assert "error_message" not in progress
    finally:
        await engine.dispose()


async def test_failed_not_affected():
    engine, factory = await _make_factory()
    try:
        async with factory() as session:
            session.add(
                SystemSetting(
                    key="v2_sync_progress",
                    value=json.dumps(
                        {"status": "failed", "error_message": "prev"}
                    ),
                    value_type="string",
                )
            )
            await session.commit()

        async with factory() as session:
            recovered = await recover_interrupted_v2_sync(session)
            assert recovered is False

        async with factory() as session:
            progress = await read_v2_sync_progress(session)
            assert progress["status"] == "failed"
            assert progress["error_message"] == "prev"
    finally:
        await engine.dispose()


async def test_no_progress_row():
    engine, factory = await _make_factory()
    try:
        async with factory() as session:
            recovered = await recover_interrupted_v2_sync(session)
            assert recovered is False

        async with factory() as session:
            progress = await read_v2_sync_progress(session)
            assert progress == {}
    finally:
        await engine.dispose()
