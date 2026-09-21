"""R8 one-shot rolling verification production-state tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.modules.indexing.domain.directory_fingerprint import generate_fingerprint
from cloudsite.modules.indexing.infrastructure.dirty_scope_repository import DirtyScopeRepository
from cloudsite.modules.indexing.infrastructure.rolling_verification import (
    RollingVerificationService,
)
from cloudsite.modules.indexing.infrastructure.verification_state_repository import (
    VerificationStateRepository,
)
from cloudsite.modules.providers.contracts.public import ProviderScanRoot
from cloudsite.platform.db import StateBase


_NOW = datetime(2026, 9, 21, 7, 0, tzinfo=timezone.utc)


class _Provider:
    def __init__(self, tree: dict[str, list[dict]], fail_paths: set[str] | None = None):
        self.tree = tree
        self.fail_paths = fail_paths or set()
        self.calls: list[str] = []

    async def list_path(self, path: str, refresh: bool = False, strict: bool = False):
        self.calls.append(path)
        if path in self.fail_paths:
            raise RuntimeError(f"provider failed: {path}")
        return list(self.tree.get(path, []))

    async def get_metadata(self, path: str):
        return {"name": path.rsplit("/", 1)[-1]}


def _root() -> ProviderScanRoot:
    return ProviderScanRoot(
        root_mapping_id=9001,
        content_type="software",
        display_name="Apps",
        storage_path="/apps",
    )


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


async def _seed_root(session) -> None:
    await session.execute(
        text(
            "INSERT INTO content_root_mappings "
            "(id, connection_id, content_type, display_name, alist_path, enabled, "
            "sort_order, home_order, created_at, updated_at) "
            "VALUES (9001, 1, 'software', 'Apps', '/apps', 1, 0, 0, "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
    )
    await session.commit()


def _fp(path: str, items: list[dict]) -> str:
    normalized = []
    for item in items:
        is_dir = bool(item.get("is_dir"))
        normalized.append(
            {
                "name": item["name"],
                "is_dir": is_dir,
                "size": None if is_dir else int(item.get("size") or 0),
                "modified": item.get("modified") or item.get("updated_at") or "",
                "provider_object_id": "",
            }
        )
    return generate_fingerprint(path, normalized).hash


async def test_verification_detects_change_reopens_dirty_and_isolates_failure(tmp_path):
    engine, factory = await _store(tmp_path)
    unchanged_items = [
        {
            "name": "same.zip",
            "is_dir": False,
            "size": 10,
            "modified": "2026-09-20T00:00:00Z",
        }
    ]
    old_changed_items = [
        {
            "name": "old.zip",
            "is_dir": False,
            "size": 1,
            "modified": "2026-09-20T00:00:00Z",
        }
    ]
    new_changed_items = [
        {
            "name": "new.zip",
            "is_dir": False,
            "size": 2,
            "modified": "2026-09-21 00:00:00+00:00",
        }
    ]
    provider = _Provider(
        {
            "/apps/unchanged": unchanged_items,
            "/apps/changed": new_changed_items,
        },
        fail_paths={"/apps/failing"},
    )

    try:
        async with factory() as session:
            await _seed_root(session)
            states = VerificationStateRepository(session)
            old_time = (_NOW - timedelta(days=40)).isoformat()
            await states.upsert(
                9001,
                "/apps/unchanged",
                fingerprint=_fp("/apps/unchanged", unchanged_items),
                child_count=1,
                last_verified_at=old_time,
            )
            await states.upsert(
                9001,
                "/apps/changed",
                fingerprint=_fp("/apps/changed", old_changed_items),
                child_count=1,
                last_verified_at=old_time,
            )
            await states.upsert(
                9001,
                "/apps/failing",
                fingerprint="known-good",
                child_count=1,
                last_verified_at=old_time,
            )
            dirty = DirtyScopeRepository(session)
            dirty_id = await dirty.add(
                9001,
                "/apps/changed",
                reason="old_mismatch",
                priority=1,
            )
            await dirty.resolve(dirty_id)
            await session.commit()

        async with factory() as session:
            states = VerificationStateRepository(session)
            dirty = DirtyScopeRepository(session)
            summary = await RollingVerificationService(batch_size=10).verify_root(
                provider=provider,
                root=_root(),
                verification_state=states,
                dirty_scopes=dirty,
                now=_NOW,
            )
            await session.commit()

        assert summary.status == "partial"
        assert summary.selected == 3
        assert summary.checked == 2
        assert summary.unchanged == 1
        assert summary.dirty == 1
        assert summary.failed == 1
        assert summary.dirty_paths == ["/apps/changed"]
        assert summary.failed_paths == ["/apps/failing"]

        async with factory() as session:
            states = VerificationStateRepository(session)
            dirty = DirtyScopeRepository(session)

            unchanged = await states.get(9001, "/apps/unchanged")
            changed = await states.get(9001, "/apps/changed")
            failing = await states.get(9001, "/apps/failing")
            reopened = await dirty.get_by_path(9001, "/apps/changed")
            no_dirty = await dirty.get_by_path(9001, "/apps/unchanged")

            assert unchanged is not None
            assert unchanged.last_verified_at == _NOW.isoformat()
            assert unchanged.last_changed_at is None

            assert changed is not None
            assert changed.fingerprint == _fp("/apps/changed", new_changed_items)
            assert changed.last_verified_at == _NOW.isoformat()
            assert changed.last_changed_at == _NOW.isoformat()

            assert failing is not None
            assert failing.fingerprint == "known-good"
            assert failing.last_verified_at == (
                _NOW - timedelta(days=40)
            ).isoformat()
            assert failing.last_error_code == "RuntimeError"
            assert "provider failed" in (failing.last_error_message or "")

            assert reopened is not None
            assert reopened.status == "pending"
            assert reopened.reason == "verification_mismatch"
            assert reopened.priority > 1
            assert reopened.last_error_code is None
            assert reopened.last_error_message is None
            assert no_dirty is None
    finally:
        await engine.dispose()


async def test_verification_requires_durable_baseline(tmp_path):
    engine, factory = await _store(tmp_path)
    provider = _Provider({"/apps": []})
    try:
        async with factory() as session:
            await _seed_root(session)

        async with factory() as session:
            summary = await RollingVerificationService(batch_size=10).verify_root(
                provider=provider,
                root=_root(),
                verification_state=VerificationStateRepository(session),
                dirty_scopes=DirtyScopeRepository(session),
                now=_NOW,
            )

        assert summary.status == "baseline_required"
        assert summary.selected == 0
        assert provider.calls == []
    finally:
        await engine.dispose()


async def test_verification_ignores_cloudsite_internal_entries(tmp_path):
    engine, factory = await _store(tmp_path)
    visible = [
        {
            "name": "app.zip",
            "is_dir": False,
            "size": 5,
            "modified": "2026-09-20T00:00:00Z",
        }
    ]
    provider = _Provider(
        {
            "/apps": visible
            + [
                {
                    "name": ".cloudsite",
                    "is_dir": True,
                    "modified": "2026-09-21T00:00:00Z",
                }
            ]
        }
    )
    try:
        async with factory() as session:
            await _seed_root(session)
            states = VerificationStateRepository(session)
            await states.upsert(
                9001,
                "/apps",
                fingerprint=_fp("/apps", visible),
                child_count=1,
                last_verified_at=(_NOW - timedelta(days=40)).isoformat(),
            )
            await session.commit()

        async with factory() as session:
            summary = await RollingVerificationService(batch_size=1).verify_root(
                provider=provider,
                root=_root(),
                verification_state=VerificationStateRepository(session),
                dirty_scopes=DirtyScopeRepository(session),
                now=_NOW,
            )
            await session.commit()

        assert summary.status == "success"
        assert summary.checked == 1
        assert summary.unchanged == 1
        assert summary.dirty == 0
    finally:
        await engine.dispose()
