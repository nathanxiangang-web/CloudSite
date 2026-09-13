"""Regression: standard run_sync must scan every enabled AList connection.

Previously run_sync called load_client_and_roots which uses .limit(1), so only
the first enabled connection was scanned. With two enabled connections, only the
first root appeared in the index. These tests prove run_sync now uses
load_all_connections_and_roots and indexes roots from every enabled connection,
while preserving per-root error isolation, accurate roots_total, and client
cleanup. Disabling one connection leaves the other active.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import indexer, search
from cloudsite.crypto import encrypt_secret
from cloudsite.database import IndexBase, StateBase
from cloudsite.models import (
    AListConnection,
    ContentRootMapping,
    Folder,
    Resource,
    SyncRootResult,
    SyncRun,
)

_LISTINGS: dict[str, dict[str, list[dict]]] = {}


class _FakeAListClient:
    """AList client stub that returns a fixed listing per base_url and path."""

    def __init__(self, base_url, username, password, token=""):
        self.base_url = base_url
        self.username = username
        self.password = password
        self.token = token

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def list_path(self, path, refresh=False, strict=False):
        return list(_LISTINGS.get(self.base_url, {}).get(path, []))


async def _factories(monkeypatch):
    state_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    index_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    index_factory = async_sessionmaker(index_engine, expire_on_commit=False)
    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)
    async with index_engine.begin() as conn:
        await conn.exec_driver_sql(
            "CREATE VIRTUAL TABLE search_fts USING fts5("
            "object_id UNINDEXED, object_type UNINDEXED, name, extension, "
            "content_type UNINDEXED, description, tags, breadcrumb_text)"
        )
    monkeypatch.setattr(indexer, "StateSession", state_factory)
    monkeypatch.setattr(indexer, "IndexSession", index_factory)
    monkeypatch.setattr(search, "StateSession", state_factory)
    monkeypatch.setattr(search, "IndexSession", index_factory)
    monkeypatch.setattr(indexer, "AListClient", _FakeAListClient)
    return state_engine, index_engine, state_factory, index_factory


async def _seed(state_factory, *, disable_second=False):
    async with state_factory() as session:
        session.add_all(
            [
                AListConnection(
                    id=1,
                    name="primary",
                    base_url="http://alist-a.test",
                    username="admin",
                    password_ciphertext=encrypt_secret("pw-a"),
                    enabled=True,
                ),
                AListConnection(
                    id=2,
                    name="secondary",
                    base_url="http://alist-b.test",
                    username="admin",
                    password_ciphertext=encrypt_secret("pw-b"),
                    enabled=not disable_second,
                ),
                ContentRootMapping(
                    id=1,
                    connection_id=1,
                    content_type="software",
                    display_name="Software A",
                    alist_path="/software-a",
                    enabled=True,
                    sort_order=0,
                ),
                ContentRootMapping(
                    id=2,
                    connection_id=2,
                    content_type="document",
                    display_name="Documents B",
                    alist_path="/docs-b",
                    enabled=True,
                    sort_order=0,
                ),
            ]
        )
        await session.commit()


def _populate_listings():
    _LISTINGS.clear()
    _LISTINGS.update(
        {
            "http://alist-a.test": {
                "/software-a": [
                    {"name": "app-a.zip", "is_dir": False, "size": 100, "modified": "2026-09-01T00:00:00Z"},
                ],
            },
            "http://alist-b.test": {
                "/docs-b": [
                    {"name": "guide-b.pdf", "is_dir": False, "size": 200, "modified": "2026-09-01T00:00:00Z"},
                ],
            },
        }
    )


async def test_run_sync_indexes_roots_from_all_enabled_connections(monkeypatch):
    """Two enabled connections with separate roots both appear in the index."""
    state_engine, index_engine, sf, ix = await _factories(monkeypatch)
    await _seed(sf)
    _populate_listings()

    result = await indexer.run_sync("manual", full=True, force=True)
    assert result["status"] == "success", result
    assert result["roots_completed"] == 2
    assert result["roots_failed"] == 0
    assert result["resources"] == 2

    async with ix() as session:
        resources = list(
            (await session.scalars(select(Resource).order_by(Resource.path))).all()
        )
        paths = [r.path for r in resources]
        assert "/software-a/app-a.zip" in paths
        assert "/docs-b/guide-b.pdf" in paths
        assert len(resources) == 2

        folders = list(
            (await session.scalars(select(Folder).order_by(Folder.path))).all()
        )
        folder_paths = [f.path for f in folders]
        assert "/software-a" in folder_paths
        assert "/docs-b" in folder_paths

        run = await session.scalar(select(SyncRun).order_by(SyncRun.id.desc()).limit(1))
        assert run.roots_total == 2
        assert run.status == "success"

    await state_engine.dispose()
    await index_engine.dispose()


async def test_disabling_one_connection_leaves_the_other_active(monkeypatch):
    """Disabling one connection leaves the other connection's root active."""
    state_engine, index_engine, sf, ix = await _factories(monkeypatch)
    await _seed(sf, disable_second=True)
    _populate_listings()

    result = await indexer.run_sync("manual", full=True, force=True)
    assert result["status"] == "success", result
    assert result["roots_completed"] == 1
    assert result["roots_failed"] == 0
    assert result["resources"] == 1

    async with ix() as session:
        resources = list(
            (await session.scalars(select(Resource).order_by(Resource.path))).all()
        )
        paths = [r.path for r in resources]
        assert "/software-a/app-a.zip" in paths
        assert "/docs-b/guide-b.pdf" not in paths
        assert len(resources) == 1

        run = await session.scalar(select(SyncRun).order_by(SyncRun.id.desc()).limit(1))
        assert run.roots_total == 1

    await state_engine.dispose()
    await index_engine.dispose()


async def test_per_root_error_isolation_continues_other_connections(monkeypatch):
    """A failing root in one connection does not block the other connection."""

    class _FailingClient:
        def __init__(self, base_url, username, password, token=""):
            self.base_url = base_url

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def list_path(self, path, refresh=False, strict=False):
            raise RuntimeError("alist-a unavailable")

    state_engine, index_engine, sf, ix = await _factories(monkeypatch)
    await _seed(sf)
    _populate_listings()

    original_client = indexer.AListClient

    def client_factory(base_url, username, password, token=""):
        if base_url == "http://alist-a.test":
            return _FailingClient(base_url, username, password, token)
        return original_client(base_url, username, password, token)

    monkeypatch.setattr(indexer, "AListClient", client_factory)

    result = await indexer.run_sync("manual", full=True, force=True)
    assert result["status"] == "partial", result
    assert result["roots_failed"] == 1
    assert result["roots_completed"] == 1

    async with ix() as session:
        resources = list(
            (await session.scalars(select(Resource).order_by(Resource.path))).all()
        )
        paths = [r.path for r in resources]
        assert "/docs-b/guide-b.pdf" in paths
        assert "/software-a/app-a.zip" not in paths

        root_results = list(
            (
                await session.scalars(
                    select(SyncRootResult).order_by(SyncRootResult.root_mapping_id)
                )
            ).all()
        )
        statuses = {r.root_mapping_id: r.status for r in root_results}
        assert statuses[1] == "failed"
        assert statuses[2] == "success"

    await state_engine.dispose()
    await index_engine.dispose()
