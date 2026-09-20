"""R3 PR02: atomic root reconcile regression tests (V2 doc section 20).

Verifies that:
- reconcile runs in a single DB transaction; success leaves production
  updated and rollback untouched.
- reconcile exception triggers session.rollback(), production stays at the
  previous consistent state, and staging is preserved for retry.
- retry_reconcile_from_staging reloads the snapshot from index_scan_entries
  without rescanning, cleans staging on success, and preserves staging on
  failure.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from cloudsite.database import StateBase
from cloudsite.modules.indexing.application.reconcile import (
    ReconcileResult,
    ReconcileService,
)
from cloudsite.modules.indexing.application.reconcile_retry import (
    retry_reconcile_from_staging,
)
from cloudsite.modules.indexing.domain.snapshot import (
    CategorySnapshot,
    SnapshotEntry,
)
from cloudsite.modules.indexing.infrastructure.legacy_bridge import run_indexing_v2
from cloudsite.modules.indexing.infrastructure.provider_adapter import (
    ProviderCapabilities,
)
from cloudsite.modules.indexing.infrastructure.repository import (
    IndexedEntry,
    IndexingRepository,
)


_NOW = datetime(2026, 9, 20, tzinfo=timezone.utc)


# ---------------------------------------------------------------------
# Fakes for run_indexing_v2 atomic-reconcile tests
# ---------------------------------------------------------------------

class _FakeAdapter:
    """Provider adapter backed by an in-memory catalog."""

    def __init__(self, catalog: dict[str, list[SnapshotEntry]]) -> None:
        self._catalog = catalog
        self.scan_calls: list[str] = []

    @property
    def provider_id(self) -> str:
        return "fake-provider"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(supports_scan=True)

    async def scan_category(
        self,
        category_id: str,
        *,
        cursor: str | None = None,
        limit: int | None = None,
        on_progress: Any = None,
    ) -> tuple[list[SnapshotEntry], str | None, bool]:
        self.scan_calls.append(category_id)
        return list(self._catalog.get(category_id, [])), None, True

    async def inspect(self, request):  # noqa: ANN001
        raise NotImplementedError


class _AtomicStore:
    """In-memory IndexingStore fake with commit / rollback tracking.

    ``fail_on_upsert`` makes ``upsert`` raise on the N-th call so we can
    simulate a mid-reconcile failure and verify rollback semantics.
    """

    def __init__(
        self,
        seeded: list[IndexedEntry] | None = None,
        *,
        fail_on_upsert: int | None = None,
    ) -> None:
        self._entries: dict[str, IndexedEntry] = {
            e.resource_id: e for e in (seeded or [])
        }
        self._fail_on_upsert = fail_on_upsert
        self._upsert_count = 0
        self.commit_calls_count = 0
        self.rollback_call_count = 0
        self._rolled_back = False

    async def list_indexed(self, *, category_id: str, provider_id: str) -> list[IndexedEntry]:
        return [
            e for e in self._entries.values()
            if e.category_id == category_id and e.provider_id == provider_id
        ]

    async def upsert(self, entries: list[IndexedEntry]) -> int:
        self._upsert_count += 1
        if self._fail_on_upsert is not None and self._upsert_count >= self._fail_on_upsert:
            raise RuntimeError("upsert exploded")
        if self._rolled_back:
            return 0
        for e in entries:
            self._entries[e.resource_id] = e
        return len(entries)

    async def remove(self, resource_ids: list[str]) -> int:
        if self._rolled_back:
            return 0
        removed = 0
        for rid in resource_ids:
            if rid in self._entries:
                del self._entries[rid]
                removed += 1
        return removed

    async def touch_unchanged(self, resource_ids: list[str]) -> int:
        if self._rolled_back:
            return 0
        return len(resource_ids)

    async def commit(self) -> None:
        self.commit_call_count += 1

    async def rollback(self) -> None:
        self.rollback_call_count += 1
        self._rolled_back = True


def _snap_entry(rid: str, name: str | None = None) -> SnapshotEntry:
    nm = name or rid
    return SnapshotEntry(
        resource_id=rid,
        path=f"/cat/{nm}",
        name=nm,
        size=100,
        modified_at=_NOW,
        content_hash=f"h-{rid}",
        metadata={"is_dir": False},
    )


def _indexed_entry(rid: str) -> IndexedEntry:
    return IndexedEntry(
        resource_id=rid,
        category_id="cat-1",
        provider_id="fake-provider",
        path=f"/cat/{rid}",
        name=rid,
        size=100,
        modified_at=_NOW,
        content_hash=f"h-{rid}",
        metadata={"is_dir": False},
        indexed_at=_NOW,
    )


# =====================================================================
# 1. atomic commit
# =====================================================================

async def test_reconcile_atomic_commit() -> None:
    """Normal reconcile completes without rollback; production is updated."""
    catalog = {"cat-1": [_snap_entry("r-1"), _snap_entry("r-2")]}
    adapter = _FakeAdapter(catalog)
    store = _AtomicStore()

    result = await run_indexing_v2(
        adapter=adapter,
        store=store,
        category_ids=["cat-1"],
    )

    assert result["status"] == "success"
    assert result["writes"]["added"] == 2
    assert store.rollback_call_count == 0, "rollback must not be called on success"
    production = await store.list_indexed(
        category_id="cat-1", provider_id="fake-provider",
    )
    assert {e.resource_id for e in production} == {"r-1", "r-2"}


# =====================================================================
# 2. atomic rollback
# =====================================================================

async def test_reconcile_atomic_rollback() -> None:
    """Reconcile exception triggers rollback; production unchanged."""
    catalog = {"cat-1": [_snap_entry("r-new-1"), _snap_entry("r-new-2")]}
    adapter = _FakeAdapter(catalog)
    store = _AtomicStore(
        seeded=[_indexed_entry("r-old-1")],
        fail_on_upsert=1,
    )

    result = await run_indexing_v2(
        adapter=adapter,
        store=store,
        category_ids=["cat-1"],
    )

    assert result["status"] == "partial"
    assert store.rollback_call_count == 1, "rollback must be called on exception"
    assert any("upsert exploded" in e for e in result["errors"])
    production = await store.list_indexed(
        category_id="cat-1", provider_id="fake-provider",
    )
    production_ids = {e.resource_id for e in production}
    assert "r-new-1" not in production_ids, "rolled-back writes must not be visible"
    assert "r-new-2" not in production_ids, "rolled-back writes must not be visible"


# =====================================================================
# 3. staging preserved on exception
# =====================================================================

async def test_reconcile_exception_staging_preserved(tmp_path) -> None:
    """After a reconcile exception, staging entries remain in index_scan_entries."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'staging.db'}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(StateBase.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async with factory() as session:
            await session.execute(
                text(
                    "INSERT INTO index_scan_runs "
                    "(id, root_mapping_id, status, fingerprint) "
                    "VALUES (:id, 1, 'running', 'fp')"
                ),
                {"id": "run-staged"},
            )
            await session.execute(
                text(
                    "INSERT INTO index_scan_entries "
                    "(id, scan_run_id, dir_path, resource_id, name, is_dir, "
                    "modified, metadata_hash) "
                    "VALUES (:id, :rid, :dp, :resid, :name, 0, :mod, :hash)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "rid": "run-staged",
                    "dp": "/cat/file-1.zip",
                    "resid": "staged-1",
                    "name": "file-1.zip",
                    "mod": _NOW,
                    "hash": "hash-staged-1",
                },
            )
            await session.commit()

        catalog = {"cat-1": [_snap_entry("r-fail")]}
        adapter = _FakeAdapter(catalog)
        store = _AtomicStore(fail_on_upsert=1)

        result = await run_indexing_v2(
            adapter=adapter,
            store=store,
            category_ids=["cat-1"],
        )

        assert result["status"] == "partial"
        assert store.rollback_call_count == 1

        async with factory() as session:
            count = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM index_scan_entries "
                        "WHERE scan_run_id = :rid"
                    ),
                    {"rid": "run-staged"},
                )
            ).scalar_one()
            assert count == 1, "staging entries must be preserved after reconcile failure"
    finally:
        await engine.dispose()


# =====================================================================
# Real-DB helpers for retry tests
# =====================================================================

async def _setup_retry_db(tmp_path) -> tuple[Any, Any]:
    """Create a SQLite DB with StateBase tables and seed a scan run + staging."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'retry.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO index_scan_runs "
                "(id, root_mapping_id, status, fingerprint) "
                "VALUES (:id, 1, 'running', 'fp-retry')"
            ),
            {"id": "run-retry-1"},
        )
        for i in range(3):
            await session.execute(
                text(
                    "INSERT INTO index_scan_entries "
                    "(id, scan_run_id, dir_path, resource_id, name, is_dir, "
                    "modified, metadata_hash) "
                    "VALUES (:id, :rid, :dp, :resid, :name, 0, :mod, :hash)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "rid": "run-retry-1",
                    "dp": f"/cat/file-{i}.zip",
                    "resid": f"staged-res-{i}",
                    "name": f"file-{i}.zip",
                    "mod": _NOW,
                    "hash": f"hash-{i}",
                },
            )
        await session.commit()

    return engine, factory


# =====================================================================
# 4. retry from staging succeeds
# =====================================================================

async def test_retry_reconcile_from_staging(tmp_path) -> None:
    """Retry reconcile from staging succeeds without rescanning."""
    engine, factory = await _setup_retry_db(tmp_path)
    try:
        async with factory() as session:
            store = IndexingRepository(session)
            result = await retry_reconcile_from_staging(
                "run-retry-1",
                store,
                category_id="cat-1",
                provider_id="prov-1",
            )

            assert result.writes.added == 3
            production = await store.list_indexed(
                category_id="cat-1", provider_id="prov-1",
            )
            assert {e.resource_id for e in production} == {
                "staged-res-0", "staged-res-1", "staged-res-2",
            }
    finally:
        await engine.dispose()


# =====================================================================
# 5. retry does not rescan
# =====================================================================

async def test_retry_does_not_rescan(tmp_path) -> None:
    """Retry reconcile must not invoke any provider scan method."""
    engine, factory = await _setup_retry_db(tmp_path)
    try:
        scan_invocations: list[str] = []

        class _NoScanStore(IndexingRepository):
            async def scan_category(self, *args, **kwargs):  # noqa: ANN002, ANN003
                scan_invocations.append("scan_category")
                raise NotImplementedError

        async with factory() as session:
            store = _NoScanStore(session)
            await retry_reconcile_from_staging(
                "run-retry-1",
                store,
                category_id="cat-1",
                provider_id="prov-1",
            )

            assert scan_invocations == [], "retry must not trigger any scan"
    finally:
        await engine.dispose()


# =====================================================================
# 6. retry success cleans staging
# =====================================================================

async def test_retry_success_cleans_staging(tmp_path) -> None:
    """Successful retry deletes all staging entries for the run."""
    engine, factory = await _setup_retry_db(tmp_path)
    try:
        async with factory() as session:
            store = IndexingRepository(session)
            await retry_reconcile_from_staging(
                "run-retry-1",
                store,
                category_id="cat-1",
                provider_id="prov-1",
            )

        async with factory() as session:
            count = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM index_scan_entries "
                        "WHERE scan_run_id = :rid"
                    ),
                    {"rid": "run-retry-1"},
                )
            ).scalar_one()
            assert count == 0, "staging must be cleaned after successful retry"
    finally:
        await engine.dispose()


# =====================================================================
# 7. retry failure keeps staging
# =====================================================================

async def test_retry_failure_keeps_staging(tmp_path) -> None:
    """Failed retry preserves staging entries for a subsequent attempt."""
    engine, factory = await _setup_retry_db(tmp_path)
    try:
        async with factory() as session:
            store = IndexingRepository(session)

            original_upsert = store.upsert
            call_count = 0

            async def exploding_upsert(entries):
                nonlocal call_count
                call_count += 1
                raise RuntimeError("retry boom")

            store.upsert = exploding_upsert  # type: ignore[assignment]

            with pytest.raises(RuntimeError, match="retry boom"):
                await retry_reconcile_from_staging(
                    "run-retry-1",
                    store,
                    category_id="cat-1",
                    provider_id="prov-1",
                )

        async with factory() as session:
            count = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM index_scan_entries "
                        "WHERE scan_run_id = :rid"
                    ),
                    {"rid": "run-retry-1"},
                )
            ).scalar_one()
            assert count == 3, "staging must be preserved after failed retry"
    finally:
        await engine.dispose()


# =====================================================================
# 8. multiple retries eventually succeed
# =====================================================================

async def test_multiple_retries_eventually_succeed(tmp_path) -> None:
    """Retry can be called repeatedly; once the store heals, it succeeds."""
    engine, factory = await _setup_retry_db(tmp_path)
    try:
        attempts = 0
        max_failures = 2

        async with factory() as session:
            store = IndexingRepository(session)
            real_upsert = store.upsert

            async def flaky_upsert(entries):
                nonlocal attempts
                attempts += 1
                if attempts <= max_failures:
                    raise RuntimeError(f"transient failure {attempts}")
                return await real_upsert(entries)

            store.upsert = flaky_upsert  # type: ignore[assignment]

            with pytest.raises(RuntimeError, match="transient failure 1"):
                await retry_reconcile_from_staging(
                    "run-retry-1",
                    store,
                    category_id="cat-1",
                    provider_id="prov-1",
                )

        async with factory() as session:
            count = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM index_scan_entries "
                        "WHERE scan_run_id = :rid"
                    ),
                    {"rid": "run-retry-1"},
                )
            ).scalar_one()
            assert count == 3, "staging preserved after first failed retry"

        async with factory() as session:
            store = IndexingRepository(session)
            attempts = 0
            real_upsert = store.upsert

            async def flaky_upsert2(entries):
                nonlocal attempts
                attempts += 1
                if attempts <= 1:
                    raise RuntimeError("transient failure on second retry")
                return await real_upsert(entries)

            store.upsert = flaky_upsert2  # type: ignore[assignment]

            with pytest.raises(RuntimeError, match="transient failure on second retry"):
                await retry_reconcile_from_staging(
                    "run-retry-1",
                    store,
                    category_id="cat-1",
                    provider_id="prov-1",
                )

        async with factory() as session:
            store = IndexingRepository(session)
            result = await retry_reconcile_from_staging(
                "run-retry-1",
                store,
                category_id="cat-1",
                provider_id="prov-1",
            )

            assert result.writes.added == 3

        async with factory() as session:
            count = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM index_scan_entries "
                        "WHERE scan_run_id = :rid"
                    ),
                    {"rid": "run-retry-1"},
                )
            ).scalar_one()
            assert count == 0, "staging cleaned after eventual success"
    finally:
        await engine.dispose()
