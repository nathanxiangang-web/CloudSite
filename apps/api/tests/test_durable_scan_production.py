"""Production durable-scan integration regression tests."""
from __future__ import annotations

from typing import Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from cloudsite.alist import AListError
from cloudsite.modules.indexing.infrastructure.alist_adapter import (
    AListProviderAdapter,
    _stable_id,
)
from cloudsite.modules.indexing.infrastructure.durable_provider_scan import (
    _fingerprint,
)
from cloudsite.modules.indexing.infrastructure.durable_scan_checkpoint import (
    DirCheckpoint,
    ScanRunManager,
)
from cloudsite.modules.indexing.infrastructure.durable_scan_repository import (
    DurableScanRepository,
)
from cloudsite.modules.providers.contracts.public import ProviderScanRoot
from cloudsite.platform.db import StateBase


class FakeProvider:
    def __init__(
        self,
        tree: dict[str, list[dict[str, Any]]],
        *,
        fail_paths: set[str] | None = None,
    ) -> None:
        self._tree = tree
        self._fail_paths = fail_paths or set()
        self.list_calls: list[str] = []

    async def list_path(
        self,
        path: str,
        refresh: bool = False,
        strict: bool = False,
    ) -> list[dict[str, Any]]:
        self.list_calls.append(path)
        if path in self._fail_paths:
            raise AListError(f"boom: {path}", "AL-500")
        return list(self._tree.get(path, []))

    async def get_metadata(self, path: str) -> dict[str, Any]:
        return {"name": path.rsplit("/", 1)[-1]}


def _root() -> ProviderScanRoot:
    return ProviderScanRoot(
        root_mapping_id=1,
        content_type="software",
        display_name="Root",
        storage_path="/root",
    )


def _tree() -> dict[str, list[dict[str, Any]]]:
    return {
        "/root": [
            {"name": "a", "is_dir": True},
            {"name": "b", "is_dir": True},
            {"name": "root.bin", "is_dir": False, "size": 100},
        ],
        "/root/a": [
            {"name": "a.txt", "is_dir": False, "size": 10},
            {"name": "sub", "is_dir": True},
        ],
        "/root/a/sub": [
            {"name": "deep.zip", "is_dir": False, "size": 5},
        ],
        "/root/b": [
            {"name": "b.txt", "is_dir": False, "size": 20},
        ],
    }


def _enable_foreign_keys(engine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn, _record):  # noqa: ANN001
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


async def _make_factory(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'state.db'}"
    )
    _enable_foreign_keys(engine)
    async with engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _seed_root(session: AsyncSession) -> None:
    await session.execute(
        text(
            "INSERT INTO content_root_mappings "
            "(id, connection_id, content_type, display_name, alist_path, enabled, "
            "sort_order, home_order, created_at, updated_at) "
            "VALUES (1, 1, 'software', 'Root', '/root', 1, 0, 0, "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
    )
    await session.commit()


async def test_durable_scan_checkpoints_and_completes(tmp_path):
    engine, factory = await _make_factory(tmp_path)
    try:
        async with factory() as session:
            await _seed_root(session)
            provider = FakeProvider(_tree())
            adapter = AListProviderAdapter(
                provider,
                [_root()],
                durable_session=session,
            )

            entries, cursor, complete = await adapter.scan_category(
                "root:1",
                concurrency=4,
            )

            assert cursor is None
            assert complete is True
            assert {entry.path for entry in entries} == {
                "/root",
                "/root/a",
                "/root/a/a.txt",
                "/root/a/sub",
                "/root/a/sub/deep.zip",
                "/root/b",
                "/root/b/b.txt",
                "/root/root.bin",
            }
            assert len({entry.resource_id for entry in entries}) == len(entries)

            by_path = {entry.path: entry for entry in entries}
            assert by_path["/root"].metadata["child_folder_count"] == 2
            assert by_path["/root"].metadata["resource_count"] == 1
            assert by_path["/root/a"].metadata["child_folder_count"] == 1
            assert by_path["/root/a"].metadata["resource_count"] == 1

            repo = DurableScanRepository(session)
            runs = await repo.list_scan_runs(1)
            assert len(runs) == 1
            assert runs[0].status == "completed"
            assert await repo.count_dirs(runs[0].id, "done") == 4
            assert await repo.count_entries(runs[0].id) == len(entries) - 1

            metrics = adapter.last_scan_metrics
            assert metrics["active_workers"] == 0
            assert metrics["dirs_pending"] == 0
            assert metrics["dirs_done"] == 4
            assert metrics["entries_discovered"] == len(entries)
    finally:
        await engine.dispose()


async def test_durable_scan_resumes_without_rescanning_done_dirs(tmp_path):
    engine, factory = await _make_factory(tmp_path)
    try:
        async with factory() as session:
            await _seed_root(session)
            root = _root()
            provider = FakeProvider(
                {
                    "/root/a": [
                        {"name": "leaf.txt", "is_dir": False, "size": 7},
                    ]
                }
            )
            adapter = AListProviderAdapter(
                provider,
                [root],
                durable_session=session,
            )
            repo = DurableScanRepository(session)
            manager = ScanRunManager(session)
            checkpoint = DirCheckpoint(session)

            run = await manager.start_scan(
                root.root_mapping_id,
                fingerprint=_fingerprint(root, "/root"),
            )
            await repo.add_dirs(run.id, [("/root", 0)])
            claimed = await repo.claim_dir(run.id, "/root")
            assert claimed is not None

            child = adapter._make_entry(
                resource_id=_stable_id("folder", "/root/a", root.root_mapping_id),
                path="/root/a",
                name="a",
                is_dir=True,
                modified=None,
                root=root,
                parent_path="/root",
                depth=1,
            )
            await checkpoint.checkpoint_dir(
                run.id,
                "/root",
                [child],
                [("/root/a", 1)],
            )
            await session.commit()

            entries, _, complete = await adapter.scan_category(
                "root:1",
                concurrency=2,
            )

            assert complete is True
            assert provider.list_calls == ["/root/a"]
            assert {entry.path for entry in entries} == {
                "/root",
                "/root/a",
                "/root/a/leaf.txt",
            }

            refreshed = await repo.get_scan_run(run.id)
            assert refreshed is not None
            assert refreshed.status == "completed"
            assert await repo.count_dirs(run.id, "done") == 2
    finally:
        await engine.dispose()


async def test_durable_scan_recovers_after_unexpected_interruption(tmp_path):
    class CrashingProvider(FakeProvider):
        async def list_path(self, path: str, refresh=False, strict=False):
            self.list_calls.append(path)
            raise RuntimeError("process-like interruption")

    engine, factory = await _make_factory(tmp_path)
    try:
        async with factory() as session:
            await _seed_root(session)
            first = AListProviderAdapter(
                CrashingProvider(_tree()),
                [_root()],
                durable_session=session,
            )

            try:
                await first.scan_category("root:1", concurrency=2)
            except RuntimeError as exc:
                assert "interruption" in str(exc)
            else:
                raise AssertionError("unexpected interruption must propagate")

            repo = DurableScanRepository(session)
            runs = await repo.list_scan_runs(1)
            assert len(runs) == 1
            run_id = runs[0].id
            assert runs[0].status == "running"
            assert await repo.count_dirs(run_id, "running") == 1

            provider = FakeProvider(_tree())
            resumed = AListProviderAdapter(
                provider,
                [_root()],
                durable_session=session,
            )
            entries, _, complete = await resumed.scan_category(
                "root:1",
                concurrency=2,
            )

            assert complete is True
            assert "/root" in provider.list_calls
            assert {entry.path for entry in entries} == {
                "/root",
                "/root/a",
                "/root/a/a.txt",
                "/root/a/sub",
                "/root/a/sub/deep.zip",
                "/root/b",
                "/root/b/b.txt",
                "/root/root.bin",
            }
            refreshed = await repo.get_scan_run(run_id)
            assert refreshed is not None
            assert refreshed.status == "completed"
    finally:
        await engine.dispose()


async def test_durable_scan_failure_is_partial_and_terminal(tmp_path):
    engine, factory = await _make_factory(tmp_path)
    try:
        async with factory() as session:
            await _seed_root(session)
            provider = FakeProvider(
                {
                    "/root": [{"name": "bad", "is_dir": True}],
                    "/root/bad": [],
                },
                fail_paths={"/root/bad"},
            )
            adapter = AListProviderAdapter(
                provider,
                [_root()],
                durable_session=session,
            )

            entries, _, complete = await adapter.scan_category(
                "root:1",
                concurrency=2,
            )

            assert complete is False
            assert {entry.path for entry in entries} == {
                "/root",
                "/root/bad",
            }

            repo = DurableScanRepository(session)
            runs = await repo.list_scan_runs(1)
            assert len(runs) == 1
            assert runs[0].status == "failed"
            assert await repo.count_dirs(runs[0].id, "failed") == 1
            assert await repo.count_dirs(runs[0].id, "pending") == 0
            assert await repo.count_dirs(runs[0].id, "running") == 0
    finally:
        await engine.dispose()
