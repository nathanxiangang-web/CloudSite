"""Automation parser cross-module contract tests."""

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import models as legacy_models  # noqa: F401 - register metadata
from cloudsite.models import SyncChange, SyncRun
from cloudsite.modules.indexing.contracts.public import (
    parser_seed_changes,
    parser_seed_run,
)
from cloudsite.modules.resources.contracts.public import resource_queries
from cloudsite.modules.resources.infrastructure.models import Resource
from cloudsite.platform.db import IndexBase


async def test_resources_parser_contract_returns_minimal_snapshot():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(IndexBase.metadata.create_all)

    now = datetime(2026, 9, 19, tzinfo=timezone.utc)
    async with factory() as session:
        session.add(
            Resource(
                id="r_parser",
                name="Tool-1.2.3-windows-x64.zip",
                path="/software/Tool-1.2.3-windows-x64.zip",
                parent_id=None,
                content_type="software",
                root_mapping_id=7,
                extension="zip",
                mime_type="application/zip",
                size=10,
                status="suspected_missing",
                indexed_at=now,
            )
        )
        await session.commit()

    async with factory() as session:
        view = await resource_queries(session).parser_resource(
            resource_id="r_parser"
        )
        assert view is not None
        assert view.id == "r_parser"
        assert view.name == "Tool-1.2.3-windows-x64.zip"
        assert view.path == "/software/Tool-1.2.3-windows-x64.zip"
        assert view.extension == "zip"
        assert view.mime_type == "application/zip"
        assert view.status == "suspected_missing"

        assert (
            await resource_queries(session).parser_resource(
                resource_id="missing"
            )
            is None
        )

    await engine.dispose()


async def test_indexing_parser_seed_contract_preserves_run_and_change_order():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(IndexBase.metadata.create_all)

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
        run_view = await parser_seed_run(session, sync_run_id=run_id)
        assert run_view is not None
        assert run_view.id == run_id
        assert run_view.status == "success"

        first = await parser_seed_changes(
            session,
            sync_run_id=run_id,
            after_change_id=0,
            limit=2,
        )
        assert [item.object_id for item in first] == ["r1", "f1"]

        second = await parser_seed_changes(
            session,
            sync_run_id=run_id,
            after_change_id=first[-1].id,
            limit=2,
        )
        assert [item.object_id for item in second] == ["r2"]

        assert await parser_seed_run(session, sync_run_id=999999) is None

    await engine.dispose()
