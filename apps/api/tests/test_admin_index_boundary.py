"""Admin index contract boundary regression."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import models  # noqa: F401 - register shared metadata
from cloudsite.modules.indexing.contracts.public import (
    legacy_sync_queries,
    read_v2_sync_progress,
)
from cloudsite.modules.indexing.infrastructure.legacy_models import (
    SyncChange,
    SyncRun,
)
from cloudsite.modules.resources.contracts.public import resource_queries
from cloudsite.modules.resources.infrastructure.models import Folder, Resource
from cloudsite.platform.db import IndexBase, StateBase


async def test_admin_index_resource_and_sync_views():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)

    async with factory() as index:
        index.add_all(
            [
                Folder(
                    id="f_active",
                    name="Active",
                    path="/active",
                    parent_id=None,
                    content_type="software",
                    root_mapping_id=1,
                    depth=0,
                    status="active",
                ),
                Folder(
                    id="f_missing",
                    name="Missing",
                    path="/missing",
                    parent_id=None,
                    content_type="software",
                    root_mapping_id=1,
                    depth=0,
                    status="missing",
                ),
                Resource(
                    id="r_active",
                    name="a.zip",
                    path="/active/a.zip",
                    parent_id="f_active",
                    content_type="software",
                    root_mapping_id=1,
                    extension="zip",
                    mime_type="application/zip",
                    size=10,
                    status="active",
                ),
                Resource(
                    id="r_missing",
                    name="m.zip",
                    path="/active/m.zip",
                    parent_id="f_active",
                    content_type="software",
                    root_mapping_id=1,
                    extension="zip",
                    mime_type="application/zip",
                    size=20,
                    status="missing",
                ),
            ]
        )
        run = SyncRun(
            sync_type="manual",
            status="success",
            folders_scanned=3,
            resources_scanned=7,
            added_count=2,
            updated_count=1,
            removed_count=1,
            duration_ms=1250,
            current_path="/active",
            roots_total=2,
            roots_completed=2,
            roots_failed=0,
        )
        index.add(run)
        await index.flush()
        index.add(
            SyncChange(
                sync_run_id=run.id,
                object_type="resource",
                object_id="r_active",
                change_type="updated",
                old_path="/old/a.zip",
                new_path="/active/a.zip",
            )
        )
        await index.commit()
        run_id = run.id

    async with factory() as index:
        resources = resource_queries(index)
        counts = await resources.admin_index_counts()
        assert counts.folders == 1
        assert counts.resources == 1

        folders = await resources.admin_index_folders()
        assert [item.id for item in folders] == ["f_active"]
        assert folders[0].to_dict()["path"] == "/active"

        detail = await resources.admin_index_folder(
            folder_id="f_active",
        )
        assert detail is not None
        payload = detail.to_dict()
        assert payload["direct_resource_count"] == 1
        assert payload["root_mapping_id"] == 1

        assert await resources.admin_index_folder(
            folder_id="f_missing",
        ) is None

        sync = legacy_sync_queries(index)
        runs = await sync.list_runs(limit=10)
        assert len(runs) == 1
        assert runs[0].id == run_id
        assert runs[0].sync_type == "manual"
        assert runs[0].resources_scanned == 7
        assert runs[0].to_dict()["current_path"] == "/active"

        changes = await sync.list_recent_changes(
            sync_run_id=run_id,
            limit=10,
        )
        assert len(changes) == 1
        assert changes[0].old_path == "/old/a.zip"
        assert changes[0].new_path == "/active/a.zip"

    await engine.dispose()


async def test_v2_progress_read_without_system_setting_orm():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)

    async with factory() as state:
        await state.execute(
            text(
                "INSERT INTO system_settings"
                "(key, value, value_type) "
                "VALUES (:key, :value, 'string')"
            ),
            {
                "key": "v2_sync_progress",
                "value": (
                    '{"status":"running","categories_done":2,'
                    '"categories_total":4,"elapsed_seconds":9,'
                    '"current_path":"/apps","entries_scanned":12}'
                ),
            },
        )
        await state.commit()

    async with factory() as state:
        progress = await read_v2_sync_progress(state)
        assert progress["status"] == "running"
        assert progress["categories_done"] == 2
        assert progress["entries_scanned"] == 12

    await engine.dispose()
