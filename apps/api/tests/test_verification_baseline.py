"""R8 verification baseline promotion from durable scan staging."""

from __future__ import annotations

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.modules.indexing.domain.directory_fingerprint import generate_fingerprint
from cloudsite.modules.indexing.infrastructure.verification_baseline import (
    seed_verification_baseline_from_durable_run,
)
from cloudsite.modules.indexing.infrastructure.verification_state_repository import (
    VerificationStateRepository,
)
from cloudsite.platform.db import StateBase


def _enable_foreign_keys(engine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn, _record):  # noqa: ANN001
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


async def _store(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    _enable_foreign_keys(engine)
    async with engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _seed_root(session, root_id: int = 7001) -> None:
    await session.execute(
        text(
            "INSERT INTO content_root_mappings "
            "(id, connection_id, content_type, display_name, alist_path, enabled, "
            "sort_order, home_order, created_at, updated_at) "
            "VALUES (:id, 1, 'software', 'Apps', '/apps', 1, 0, 0, "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {"id": root_id},
    )


async def _seed_run(session, *, status: str = "completed", root_id: int = 7001) -> None:
    await session.execute(
        text(
            "INSERT INTO index_scan_runs "
            "(id, root_mapping_id, status, started_at, finished_at) "
            "VALUES ('run-1', :rid, :status, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {"rid": root_id, "status": status},
    )


async def test_completed_run_promotes_full_directory_baseline(tmp_path):
    engine, factory = await _store(tmp_path)
    verified_at = "2026-09-21T06:30:00+00:00"
    try:
        async with factory() as session:
            await _seed_root(session)
            await _seed_run(session)
            await session.execute(
                text(
                    "INSERT INTO index_scan_dirs "
                    "(id, scan_run_id, path, depth, status, entry_count) VALUES "
                    "('d-root', 'run-1', '/apps', 0, 'done', 2), "
                    "('d-empty', 'run-1', '/apps/empty', 1, 'done', 0)"
                )
            )
            await session.execute(
                text(
                    "INSERT INTO index_scan_entries "
                    "(id, scan_run_id, dir_path, path, parent_path, resource_id, "
                    "name, is_dir, size, modified, metadata_json) VALUES "
                    "('e1', 'run-1', '/apps', '/apps/empty', '/apps', 'folder-empty', "
                    "'empty', 1, NULL, NULL, '{}'), "
                    "('e2', 'run-1', '/apps', '/apps/tool.zip', '/apps', 'resource-tool', "
                    "'tool.zip', 0, 42, '2026-09-21T01:00:00+00:00', '{}')"
                )
            )
            states = VerificationStateRepository(session)
            await states.upsert(
                7001,
                "/apps",
                fingerprint="old-fingerprint",
                child_count=1,
                last_verified_at="2026-09-20T00:00:00+00:00",
            )
            await states.upsert(7001, "/stale", fingerprint="stale", child_count=9)
            await session.commit()

            count = await seed_verification_baseline_from_durable_run(
                session,
                root_mapping_id=7001,
                run_id="run-1",
                verified_at=verified_at,
            )
            await session.commit()

        async with factory() as session:
            states = VerificationStateRepository(session)
            root = await states.get(7001, "/apps")
            empty = await states.get(7001, "/apps/empty")
            stale = await states.get(7001, "/stale")

            assert count == 2
            assert root is not None
            expected = generate_fingerprint(
                "/apps",
                [
                    {
                        "name": "empty",
                        "is_dir": True,
                        "size": None,
                        "modified": None,
                        "provider_object_id": "",
                    },
                    {
                        "name": "tool.zip",
                        "is_dir": False,
                        "size": 42,
                        "modified": "2026-09-21T01:00:00+00:00",
                        "provider_object_id": "",
                    },
                ],
            )
            assert root.fingerprint == expected.hash
            assert root.child_count == 2
            assert root.last_verified_at == verified_at
            assert root.last_changed_at == verified_at

            assert empty is not None
            assert empty.child_count == 0
            assert empty.fingerprint == generate_fingerprint("/apps/empty", []).hash
            assert empty.last_verified_at == verified_at
            assert empty.last_changed_at is None
            assert stale is None
    finally:
        await engine.dispose()


async def test_partial_or_failed_run_cannot_replace_baseline(tmp_path):
    engine, factory = await _store(tmp_path)
    try:
        async with factory() as session:
            await _seed_root(session)
            await _seed_run(session, status="failed")
            states = VerificationStateRepository(session)
            await states.upsert(7001, "/apps", fingerprint="known-good", child_count=3)
            await session.commit()

            with pytest.raises(ValueError, match="not complete"):
                await seed_verification_baseline_from_durable_run(
                    session,
                    root_mapping_id=7001,
                    run_id="run-1",
                )
            await session.rollback()

        async with factory() as session:
            record = await VerificationStateRepository(session).get(7001, "/apps")
            assert record is not None
            assert record.fingerprint == "known-good"
            assert record.child_count == 3
    finally:
        await engine.dispose()


async def test_completed_run_with_unfinished_directory_is_rejected(tmp_path):
    engine, factory = await _store(tmp_path)
    try:
        async with factory() as session:
            await _seed_root(session)
            await _seed_run(session)
            await session.execute(
                text(
                    "INSERT INTO index_scan_dirs "
                    "(id, scan_run_id, path, depth, status, entry_count) "
                    "VALUES ('d-root', 'run-1', '/apps', 0, 'pending', 0)"
                )
            )
            await session.commit()

            with pytest.raises(ValueError, match="unfinished"):
                await seed_verification_baseline_from_durable_run(
                    session,
                    root_mapping_id=7001,
                    run_id="run-1",
                )
    finally:
        await engine.dispose()
