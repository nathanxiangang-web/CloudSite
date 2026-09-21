"""R10 PR02: ProviderSyncStateRepository tests (V2 doc section 27).

Tests cursor persistence CRUD over the provider_sync_state table.
Uses in-memory SQLite async session.
"""
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from cloudsite.modules.providers.infrastructure.sync_state_repository import (
    ProviderSyncStateRecord,
    ProviderSyncStateRepository,
)


_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS provider_sync_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    connection_id INTEGER NOT NULL,
    root_mapping_id INTEGER,
    strategy TEXT NOT NULL DEFAULT 'rolling',
    cursor TEXT,
    cursor_version INTEGER NOT NULL DEFAULT 0,
    provider_generation TEXT NOT NULL DEFAULT '',
    last_delta_at TEXT,
    last_full_verify_at TEXT,
    status TEXT NOT NULL DEFAULT 'idle',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(connection_id, root_mapping_id)
)
"""


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.execute(text(_CREATE_SQL))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as sess:
        yield sess
    await engine.dispose()


@pytest.mark.asyncio
class TestProviderSyncStateRepository:
    async def test_get_returns_none_when_not_found(self, session: AsyncSession):
        repo = ProviderSyncStateRepository(session)
        result = await repo.get(connection_id=1, root_mapping_id=1)
        assert result is None

    async def test_upsert_creates_new_row(self, session: AsyncSession):
        repo = ProviderSyncStateRepository(session)
        await repo.upsert(
            connection_id=1,
            root_mapping_id=1,
            strategy="delta",
            cursor="abc",
        )
        record = await repo.get(connection_id=1, root_mapping_id=1)
        assert record is not None
        assert record.connection_id == 1
        assert record.root_mapping_id == 1
        assert record.strategy == "delta"
        assert record.cursor == "abc"
        assert record.cursor_version == 0
        assert record.status == "idle"

    async def test_upsert_updates_existing_row(self, session: AsyncSession):
        repo = ProviderSyncStateRepository(session)
        await repo.upsert(connection_id=1, root_mapping_id=1, strategy="rolling")
        await repo.upsert(
            connection_id=1,
            root_mapping_id=1,
            strategy="delta",
            cursor="new-cursor",
            cursor_version=5,
        )
        record = await repo.get(connection_id=1, root_mapping_id=1)
        assert record is not None
        assert record.strategy == "delta"
        assert record.cursor == "new-cursor"
        assert record.cursor_version == 5

    async def test_update_cursor(self, session: AsyncSession):
        repo = ProviderSyncStateRepository(session)
        await repo.upsert(connection_id=1, root_mapping_id=1, strategy="delta")
        await repo.update_cursor(
            connection_id=1,
            root_mapping_id=1,
            cursor="next-page",
            cursor_version=2,
        )
        record = await repo.get(connection_id=1, root_mapping_id=1)
        assert record is not None
        assert record.cursor == "next-page"
        assert record.cursor_version == 2
        assert record.last_delta_at is not None

    async def test_update_cursor_without_version(self, session: AsyncSession):
        repo = ProviderSyncStateRepository(session)
        await repo.upsert(connection_id=1, root_mapping_id=1, strategy="delta")
        await repo.update_cursor(
            connection_id=1,
            root_mapping_id=1,
            cursor="page-1",
        )
        record = await repo.get(connection_id=1, root_mapping_id=1)
        assert record is not None
        assert record.cursor == "page-1"

    async def test_update_status(self, session: AsyncSession):
        repo = ProviderSyncStateRepository(session)
        await repo.upsert(connection_id=1, root_mapping_id=1)
        await repo.update_status(connection_id=1, root_mapping_id=1, status="syncing")
        record = await repo.get(connection_id=1, root_mapping_id=1)
        assert record is not None
        assert record.status == "syncing"

    async def test_delete(self, session: AsyncSession):
        repo = ProviderSyncStateRepository(session)
        await repo.upsert(connection_id=1, root_mapping_id=1)
        await repo.delete(connection_id=1, root_mapping_id=1)
        record = await repo.get(connection_id=1, root_mapping_id=1)
        assert record is None

    async def test_supports_null_root_mapping_id(self, session: AsyncSession):
        repo = ProviderSyncStateRepository(session)
        await repo.upsert(connection_id=1, root_mapping_id=None, strategy="delta")
        record = await repo.get(connection_id=1, root_mapping_id=None)
        assert record is not None
        assert record.root_mapping_id is None
        assert record.strategy == "delta"

    async def test_separate_rows_per_connection(self, session: AsyncSession):
        repo = ProviderSyncStateRepository(session)
        await repo.upsert(connection_id=1, root_mapping_id=1, cursor="c1")
        await repo.upsert(connection_id=2, root_mapping_id=1, cursor="c2")
        r1 = await repo.get(connection_id=1, root_mapping_id=1)
        r2 = await repo.get(connection_id=2, root_mapping_id=1)
        assert r1 is not None and r2 is not None
        assert r1.cursor == "c1"
        assert r2.cursor == "c2"

    async def test_upsert_rejects_unknown_field(self, session: AsyncSession):
        repo = ProviderSyncStateRepository(session)
        with pytest.raises(ValueError, match="unsupported"):
            await repo.upsert(connection_id=1, root_mapping_id=1, bogus="x")

    async def test_record_is_frozen(self, session: AsyncSession):
        repo = ProviderSyncStateRepository(session)
        await repo.upsert(connection_id=1, root_mapping_id=1)
        record = await repo.get(connection_id=1, root_mapping_id=1)
        assert record is not None
        with pytest.raises(AttributeError):
            record.cursor = "mutated"  # type: ignore[misc]