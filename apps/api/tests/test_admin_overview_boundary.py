"""Regression coverage for admin Overview read boundaries."""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.database import IndexBase, StateBase
from cloudsite.models import (
    AListConnection,
    DownloadEvent,
    Folder,
    OperationLog,
    Resource,
    SystemSetting,
)
from cloudsite.modules.delivery.contracts.public import count_failed_downloads
from cloudsite.modules.indexing.contracts.public import read_v2_sync_progress
from cloudsite.modules.providers.contracts.public import provider_connected
from cloudsite.modules.resources.contracts.public import resource_queries
from cloudsite.platform.observability import recent_operation_logs


async def _stores():
    state_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    index_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    state_factory = async_sessionmaker(
        state_engine,
        expire_on_commit=False,
    )
    index_factory = async_sessionmaker(
        index_engine,
        expire_on_commit=False,
    )
    async with state_engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as connection:
        await connection.run_sync(IndexBase.metadata.create_all)
    return state_engine, index_engine, state_factory, index_factory


async def test_overview_metrics_stay_behind_owner_boundaries():
    (
        state_engine,
        index_engine,
        state_factory,
        index_factory,
    ) = await _stores()

    async with state_factory() as state:
        state.add(
            AListConnection(
                id=1,
                enabled=True,
                last_test_status="success",
            )
        )
        state.add_all(
            [
                DownloadEvent(
                    resource_id="r1",
                    result="failed",
                ),
                DownloadEvent(
                    resource_id="r2",
                    result="success",
                ),
                OperationLog(
                    module="overview",
                    action="first",
                    message="first",
                ),
                OperationLog(
                    module="overview",
                    action="second",
                    message="second",
                ),
                SystemSetting(
                    key="v2_sync_progress",
                    value=(
                        '{"status":"completed","categories_done":2,'
                        '"categories_total":2,"elapsed_seconds":7,'
                        '"current_path":"","entries_scanned":42}'
                    ),
                ),
            ]
        )
        await state.commit()

        assert await count_failed_downloads(state) == 1
        assert await provider_connected(state) is True
        progress = await read_v2_sync_progress(state)
        assert progress["status"] == "completed"
        assert progress["categories_done"] == 2
        assert progress["entries_scanned"] == 42
        logs = await recent_operation_logs(state, limit=2)
        assert [row["message"] for row in logs] == [
            "second",
            "first",
        ]

    async with index_factory() as index:
        index.add_all(
            [
                Folder(
                    id="f1",
                    name="folder",
                    path="/folder",
                    content_type="software",
                    status="active",
                ),
                Resource(
                    id="r1",
                    name="software",
                    path="/software",
                    content_type="software",
                    status="active",
                ),
                Resource(
                    id="r2",
                    name="image",
                    path="/image",
                    content_type="image",
                    status="active",
                ),
                Resource(
                    id="r3",
                    name="missing",
                    path="/missing",
                    content_type="video",
                    status="missing",
                ),
            ]
        )
        await index.commit()

        queries = resource_queries(index)
        counts = await queries.admin_index_counts()
        assert counts.resources == 2
        assert counts.folders == 1
        assert await queries.admin_content_type_counts(
            content_types=(
                "software",
                "image",
                "video",
                "document",
                "file",
            )
        ) == {
            "software": 1,
            "image": 1,
            "video": 0,
            "document": 0,
            "file": 0,
        }

    await state_engine.dispose()
    await index_engine.dispose()
