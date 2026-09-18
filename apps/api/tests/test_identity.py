from datetime import datetime, timezone
import sqlite3

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import main
from cloudsite.database import IndexBase, StateBase
from cloudsite.identity import IdentityObservation, identity_fingerprint, resolve_resource_identities
from cloudsite.identity import migration

from cloudsite.models import (
    CollectionItem,
    DownloadEvent,
    Resource,
    ResourceIdentity,
    ResourceIdentityHistory,
    ResourceIdentityCandidate,
    Share,
    Folder,
    SyncCycle,
    SyncCycleItem,
    SyncRun,
    SystemSetting,
)


NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)


def observation(path: str, *, size: int = 42, modified_at: datetime = NOW) -> IdentityObservation:
    return IdentityObservation(
        path=path,
        name=path.rsplit("/", 1)[-1],
        root_mapping_id=1,
        size=size,
        modified_at=modified_at,
        extension="zip",
        mime_type="application/zip",
    )


async def state_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)
    return engine, factory


async def seed_identity(factory, resource_id: str, path: str, *, size: int = 42):
    fingerprint = identity_fingerprint(
        size=size,
        modified_at=NOW,
        extension="zip",
        mime_type="application/zip",
    )
    async with factory() as session:
        session.add(
            ResourceIdentity(
                resource_id=resource_id,
                current_path=path,
                root_mapping_id=1,
                status="active",
                first_seen_at=NOW,
                last_seen_at=NOW,
                last_name=path.rsplit("/", 1)[-1],
                last_extension="zip",
                last_mime_type="application/zip",
                last_size=size,
                last_modified_at=NOW,
                identity_fingerprint=fingerprint,
                created_from="legacy_migration",
                updated_at=NOW,
            )
        )
        await session.commit()


async def test_exact_path_and_rename_preserve_resource_id():
    engine, factory = await state_factory()
    await seed_identity(factory, "r_legacy", "/软件/A.zip")
    async with factory() as session:
        exact = await resolve_resource_identities(
            session,
            [observation("/软件/A.zip")],
            visible_paths={"/软件/A.zip"},
        )
    assert exact[0].resource_id == "r_legacy"
    assert exact[0].match_type == "current_path"

    async with factory() as session:
        renamed = await resolve_resource_identities(
            session,
            [observation("/软件/B.zip")],
            visible_paths={"/软件/B.zip"},
            allowed_candidate_paths={"/软件/A.zip"},
        )
    assert renamed[0].resource_id == "r_legacy"
    assert renamed[0].match_type == "rename"
    async with factory() as session:
        identity = await session.get(ResourceIdentity, "r_legacy")
        assert identity.current_path == "/软件/B.zip"
        assert int(await session.scalar(select(func.count()).select_from(ResourceIdentityHistory)) or 0) == 1
    await engine.dispose()


async def test_copy_and_reused_old_path_receive_new_ids():
    engine, factory = await state_factory()
    await seed_identity(factory, "r_original", "/a/A.zip")
    async with factory() as session:
        copied = await resolve_resource_identities(
            session,
            [observation("/a/A.zip"), observation("/b/A.zip")],
            visible_paths={"/a/A.zip", "/b/A.zip"},
        )
    assert copied[0].resource_id == "r_original"
    assert copied[1].resource_id != "r_original"
    assert copied[1].resource_id.startswith("r_")

    new_copy_id = copied[1].resource_id
    async with factory() as session:
        reused = await resolve_resource_identities(
            session,
            [observation("/b/A.zip"), observation("/a/A.zip")],
            visible_paths={"/a/A.zip", "/b/A.zip"},
        )
    assert reused[0].resource_id == new_copy_id
    assert reused[1].resource_id == "r_original"
    await engine.dispose()


async def test_move_and_ambiguous_match_are_conservative():
    engine, factory = await state_factory()
    await seed_identity(factory, "r_old", "/a/A.zip")
    async with factory() as session:
        moved = await resolve_resource_identities(
            session,
            [observation("/b/A.zip")],
            visible_paths={"/b/A.zip"},
        )
    assert moved[0].resource_id == "r_old"
    assert moved[0].match_type == "move"

    await seed_identity(factory, "r_other", "/c/A.zip")
    async with factory() as session:
        ambiguous = await resolve_resource_identities(
            session,
            [observation("/d/A.zip")],
            visible_paths={"/d/A.zip"},
        )
    assert ambiguous[0].resource_id not in {"r_old", "r_other"}
    assert ambiguous[0].match_type == "ambiguous_new"
    assert ambiguous[0].ambiguous_resource_ids == ["r_old", "r_other"]
    await engine.dispose()


async def test_022_migration_is_idempotent_and_does_zero_id_rewrites(monkeypatch):
    state_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    index_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    state_sessions = async_sessionmaker(state_engine, expire_on_commit=False)
    index_sessions = async_sessionmaker(index_engine, expire_on_commit=False)
    async with state_engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as connection:
        await connection.run_sync(IndexBase.metadata.create_all)
        await connection.exec_driver_sql(
            "CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5("
            "object_id UNINDEXED, object_type UNINDEXED, name, extension, "
            "content_type UNINDEXED, description, tags, breadcrumb_text, "
            "tokenize='unicode61 remove_diacritics 2')"
        )
    async with index_sessions() as session:
        session.add(
            Resource(
                id="r_path_hash_legacy",
                name="A.zip",
                path="/软件/A.zip",
                content_type="software",
                root_mapping_id=1,
                extension="zip",
                mime_type="application/zip",
                size=42,
                modified_at=NOW,
                indexed_at=NOW,
                status="active",
            )
        )
        await session.commit()
    async with state_sessions() as session:
        session.add_all(
            [
                CollectionItem(collection_id=1, resource_id="r_path_hash_legacy"),
                Share(token="share", object_type="resource", object_id="r_path_hash_legacy"),
                DownloadEvent(resource_id="r_path_hash_legacy", result="success"),
            ]
        )
        await session.commit()

    monkeypatch.setattr(migration, "StateSession", state_sessions)
    monkeypatch.setattr(migration, "IndexSession", index_sessions)
    assert await migration.migrate_stable_resource_ids() == 1
    assert await migration.migrate_stable_resource_ids() == 1

    async with index_sessions() as session:
        resource = await session.get(Resource, "r_path_hash_legacy")
        assert resource.path == "/软件/A.zip"
    async with state_sessions() as session:
        identity = await session.get(ResourceIdentity, "r_path_hash_legacy")
        assert identity.current_path == "/软件/A.zip"
        assert int(await session.scalar(select(func.count()).select_from(ResourceIdentityHistory)) or 0) == 1
        assert (await session.scalar(select(CollectionItem.resource_id))) == "r_path_hash_legacy"
        assert (await session.scalar(select(Share.object_id))) == "r_path_hash_legacy"
        assert (await session.scalar(select(DownloadEvent.resource_id))) == "r_path_hash_legacy"

    await state_engine.dispose()
    await index_engine.dispose()


async def test_pre_migration_backup_is_consistent_and_idempotent(tmp_path):
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    async with state_engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as connection:
        await connection.run_sync(IndexBase.metadata.create_all)
        await connection.exec_driver_sql(
            "CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5("
            "object_id UNINDEXED, object_type UNINDEXED, name, extension, "
            "content_type UNINDEXED, description, tags, breadcrumb_text, "
            "tokenize='unicode61 remove_diacritics 2')"
        )
        await connection.execute(
            Resource.__table__.insert().values(
                id="r_legacy",
                name="A.zip",
                path="/A.zip",
                content_type="file",
                extension="zip",
                mime_type="application/zip",
                size=42,
                status="active",
            )
        )
    await state_engine.dispose()
    await index_engine.dispose()

    target = migration.backup_stable_id_databases(tmp_path)
    assert target == tmp_path / ".codex-backups" / "pre-0.3.0-stable-id"
    assert migration.backup_stable_id_databases(tmp_path) == target
    with sqlite3.connect(target / "index.db") as database:
        assert database.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert database.execute("SELECT id FROM resources").fetchone()[0] == "r_legacy"


async def test_identity_diagnostics_require_real_admin_session(monkeypatch):
    state_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    index_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    state_sessions = async_sessionmaker(state_engine, expire_on_commit=False)
    index_sessions = async_sessionmaker(index_engine, expire_on_commit=False)
    async with state_engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as connection:
        await connection.run_sync(IndexBase.metadata.create_all)
        await connection.exec_driver_sql(
            "CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5("
            "object_id UNINDEXED, object_type UNINDEXED, name, extension, "
            "content_type UNINDEXED, description, tags, breadcrumb_text, "
            "tokenize='unicode61 remove_diacritics 2')"
        )
    monkeypatch.setattr(main, "StateSession", state_sessions)
    monkeypatch.setattr(main, "IndexSession", index_sessions)

    async with state_sessions() as session:
        session.add(SystemSetting(key="setup_completed", value="true", value_type="string"))
        await session.commit()

    await seed_identity(state_sessions, "r_legacy", "/software/A.zip")
    async with index_sessions() as session:
        session.add(
            ResourceIdentityCandidate(
                observed_path="/software/B.zip",
                observed_name="B.zip",
                root_mapping_id=1,
                candidate_resource_ids_json='["r_legacy"]',
                match_type="fingerprint",
                confidence=0.5,
                status="ambiguous",
                size=42,
                modified_at=NOW,
                extension="zip",
                mime_type="application/zip",
                fingerprint=identity_fingerprint(
                    size=42,
                    modified_at=NOW,
                    extension="zip",
                    mime_type="application/zip",
                ),
                created_at=NOW,
            )
        )
        await session.commit()

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        anonymous = await client.get("/api/admin/identities/stats")
        assert anonymous.status_code == 403
        assert anonymous.json()["detail"]["code"] == "ADMIN_REQUIRED"

        cookies = {main.SESSION_COOKIE: main.create_session_token("admin")}
        stats = await client.get("/api/admin/identities/stats", cookies=cookies)
        assert stats.status_code == 200
        assert stats.json() == {
            "total": 1,
            "legacy_seeded": 1,
            "random_new": 0,
            "rename_preserved": 0,
            "move_preserved": 0,
            "pending": 0,
            "ambiguous": 1,
            "manual_repairs": 0,
        }
        candidates = await client.get(
            "/api/admin/identities/candidates?status=open",
            cookies=cookies,
        )
        assert candidates.status_code == 200
        assert candidates.json()["items"][0]["candidate_resource_ids"] == ["r_legacy"]

    await state_engine.dispose()
    await index_engine.dispose()

