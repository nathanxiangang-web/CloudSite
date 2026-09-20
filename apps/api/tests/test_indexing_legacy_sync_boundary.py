"""Regression tests for Indexing ownership of frozen legacy sync state."""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.models import (
    FolderScanState as LegacyFolderScanState,
    SyncChange as LegacySyncChange,
    SyncCycle as LegacySyncCycle,
    SyncCycleItem as LegacySyncCycleItem,
    SyncRootResult as LegacySyncRootResult,
    SyncRun as LegacySyncRun,
)
from cloudsite.modules.indexing.contracts.public import legacy_sync_queries
from cloudsite.modules.indexing.infrastructure.legacy_models import (
    FolderScanState,
    SyncChange,
    SyncCycle,
    SyncCycleItem,
    SyncRootResult,
    SyncRun,
)
from cloudsite.platform.db import IndexBase


def test_legacy_sync_exports_are_exact_indexing_classes():
    assert LegacySyncRun is SyncRun
    assert LegacySyncRootResult is SyncRootResult
    assert LegacySyncChange is SyncChange
    assert LegacySyncCycle is SyncCycle
    assert LegacySyncCycleItem is SyncCycleItem
    assert LegacyFolderScanState is FolderScanState
    assert all(
        cls.__module__ == "cloudsite.modules.indexing.infrastructure.legacy_models"
        for cls in (
            SyncRun,
            SyncRootResult,
            SyncChange,
            SyncCycle,
            SyncCycleItem,
            FolderScanState,
        )
    )


async def test_legacy_sync_query_contract_is_read_only_and_paginated():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)

    async with factory() as session:
        run = SyncRun(sync_type="rolling_window", status="success")
        session.add(run)
        await session.flush()
        session.add_all(
            [
                SyncChange(
                    sync_run_id=run.id,
                    object_type="resource",
                    object_id="r1",
                    change_type="added",
                ),
                SyncChange(
                    sync_run_id=run.id,
                    object_type="folder",
                    object_id="f1",
                    change_type="updated",
                ),
                SyncChange(
                    sync_run_id=run.id,
                    object_type="resource",
                    object_id="r2",
                    change_type="removed",
                ),
            ]
        )
        await session.commit()
        run_id = run.id

    async with factory() as session:
        queries = legacy_sync_queries(session)
        run_view = await queries.get_run(run_id)
        assert run_view is not None
        assert run_view.id == run_id
        assert run_view.status == "success"

        first = await queries.list_changes(
            sync_run_id=run_id,
            after_change_id=0,
            limit=2,
        )
        assert first.has_more is True
        assert [item.object_id for item in first.items] == ["r1", "f1"]

        second = await queries.list_changes(
            sync_run_id=run_id,
            after_change_id=first.items[-1].id,
            limit=2,
        )
        assert second.has_more is False
        assert [item.object_id for item in second.items] == ["r2"]

        missing = await queries.get_run(999)
        assert missing is None

    await engine.dispose()
