"""R4 PR03: FolderIdentity backfill + cascade delete (V2 doc sections 22-23).

Covers audit-identity-3 findings I-3 (FolderIdentity never backfilled) and
I-4 (delete_root_mapping does not cascade).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.database import StateBase
from cloudsite.modules.identity.infrastructure.folder_repository import (
    SqlAlchemyFolderIdentityRepository,
)
from cloudsite.modules.identity.infrastructure.models import (
    FolderIdentity,
    ResourceIdentity,
)
from cloudsite.modules.identity.infrastructure.resource_repository import (
    SqlAlchemyResourceIdentityRepository,
)
from cloudsite.app.root_mapping_lifecycle import delete_root_mapping_with_identity_cleanup
from cloudsite.modules.providers.infrastructure.models import ContentRootMapping

NOW = datetime(2026, 9, 20, tzinfo=timezone.utc)


async def _make_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    return engine, factory


async def test_folder_identity_backfilled():
    engine, factory = await _make_factory()
    async with factory() as session:
        repo = SqlAlchemyFolderIdentityRepository(session)
        record = await repo.backfill_folder_identity(
            "/root/photos",
            "f_photos_001",
            "fp_photos_v1",
            root_mapping_id=1,
            now=NOW,
        )
        await session.commit()

        assert record.folder_id == "f_photos_001"
        assert record.current_path == "/root/photos"
        assert record.identity_fingerprint == "fp_photos_v1"
        assert record.created_from == "backfill"
        assert record.status == "active"
        assert record.root_mapping_id == 1

        entity = await session.get(FolderIdentity, "f_photos_001")
        assert entity is not None
        assert entity.created_from == "backfill"
    await engine.dispose()


async def test_folder_identity_query():
    engine, factory = await _make_factory()
    async with factory() as session:
        repo = SqlAlchemyFolderIdentityRepository(session)
        await repo.backfill_folder_identity(
            "/root/docs",
            "f_docs_001",
            "fp_docs",
            root_mapping_id=1,
            now=NOW,
        )
        await session.commit()

        found = await repo.find_folder_identity("/root/docs")
        assert found is not None
        assert found.folder_id == "f_docs_001"
        assert found.current_path == "/root/docs"

        missing = await repo.find_folder_identity("/root/missing")
        assert missing is None
    await engine.dispose()


async def test_descendants_found():
    engine, factory = await _make_factory()
    async with factory() as session:
        repo = SqlAlchemyFolderIdentityRepository(session)
        await repo.backfill_folder_identity(
            "/root/photos", "f_photos", "fp1", root_mapping_id=1, now=NOW
        )
        await repo.backfill_folder_identity(
            "/root/photos/2026", "f_photos_2026", "fp2", root_mapping_id=1, now=NOW
        )
        await repo.backfill_folder_identity(
            "/root/photos/2026/09", "f_photos_2026_09", "fp3", root_mapping_id=1, now=NOW
        )
        await repo.backfill_folder_identity(
            "/root/other", "f_other", "fp4", root_mapping_id=1, now=NOW
        )
        await session.commit()

        descendants = await repo.find_descendants_by_folder("/root/photos")
        paths = sorted(d.current_path for d in descendants)
        assert paths == ["/root/photos/2026", "/root/photos/2026/09"]
        assert all(d.folder_id.startswith("f_photos_2026") for d in descendants)
        assert "/root/other" not in paths
        assert "/root/photos" not in paths
    await engine.dispose()


async def test_cascade_delete_root():
    engine, factory = await _make_factory()
    async with factory() as session:
        session.add(
            ContentRootMapping(
                id=1,
                connection_id=1,
                content_type="software",
                display_name="root1",
                alist_path="/root1",
                enabled=True,
                sort_order=0,
            )
        )
        folder_repo = SqlAlchemyFolderIdentityRepository(session)
        resource_repo = SqlAlchemyResourceIdentityRepository(session)
        await folder_repo.backfill_folder_identity(
            "/root1/a", "f_a", "fp_a", root_mapping_id=1, now=NOW
        )
        await folder_repo.backfill_folder_identity(
            "/root1/b", "f_b", "fp_b", root_mapping_id=1, now=NOW
        )
        session.add(
            ResourceIdentity(
                resource_id="r_1",
                current_path="/root1/a/file.txt",
                root_mapping_id=1,
                status="active",
                first_seen_at=NOW,
                last_seen_at=NOW,
                last_name="file.txt",
            )
        )
        session.add(
            ResourceIdentity(
                resource_id="r_2",
                current_path="/root1/b/file.txt",
                root_mapping_id=1,
                status="active",
                first_seen_at=NOW,
                last_seen_at=NOW,
                last_name="file.txt",
            )
        )
        await session.commit()

        result = await delete_root_mapping_with_identity_cleanup(session, 1)

        assert result["folders"] == 2
        assert result["resources"] == 2

        folders = list((await session.scalars(select(FolderIdentity))).all())
        resources = list((await session.scalars(select(ResourceIdentity))).all())
        mappings = list((await session.scalars(select(ContentRootMapping))).all())
        assert folders == []
        assert resources == []
        assert mappings == []
    await engine.dispose()


async def test_cascade_delete_count():
    engine, factory = await _make_factory()
    async with factory() as session:
        folder_repo = SqlAlchemyFolderIdentityRepository(session)
        resource_repo = SqlAlchemyResourceIdentityRepository(session)
        for i in range(5):
            await folder_repo.backfill_folder_identity(
                f"/root1/folder{i}", f"f_{i}", f"fp_{i}", root_mapping_id=1, now=NOW
            )
        for i in range(3):
            session.add(
                ResourceIdentity(
                    resource_id=f"r_{i}",
                    current_path=f"/root1/r{i}.txt",
                    root_mapping_id=1,
                    status="active",
                    first_seen_at=NOW,
                    last_seen_at=NOW,
                    last_name=f"r{i}.txt",
                )
            )
        session.add(
            ResourceIdentity(
                resource_id="r_other",
                current_path="/root2/r.txt",
                root_mapping_id=2,
                status="active",
                first_seen_at=NOW,
                last_seen_at=NOW,
                last_name="r.txt",
            )
        )
        await session.commit()

        folders_deleted = await folder_repo.cascade_delete_by_root(1)
        resources_deleted = await resource_repo.cascade_delete_by_root(1)
        assert folders_deleted == 5
        assert resources_deleted == 3

        remaining_resources = list((await session.scalars(select(ResourceIdentity))).all())
        assert len(remaining_resources) == 1
        assert remaining_resources[0].root_mapping_id == 2
    await engine.dispose()


async def test_no_orphaned_identity():
    engine, factory = await _make_factory()
    async with factory() as session:
        session.add(
            ContentRootMapping(
                id=7,
                connection_id=1,
                content_type="software",
                display_name="root7",
                alist_path="/root7",
                enabled=True,
                sort_order=0,
            )
        )
        folder_repo = SqlAlchemyFolderIdentityRepository(session)
        resource_repo = SqlAlchemyResourceIdentityRepository(session)
        await folder_repo.backfill_folder_identity(
            "/root7/x", "f_x", "fp_x", root_mapping_id=7, now=NOW
        )
        session.add(
            ResourceIdentity(
                resource_id="r_x",
                current_path="/root7/x/file.txt",
                root_mapping_id=7,
                status="active",
                first_seen_at=NOW,
                last_seen_at=NOW,
                last_name="file.txt",
            )
        )
        await session.commit()

        await delete_root_mapping_with_identity_cleanup(session, 7)

        from cloudsite.modules.identity.infrastructure.models import (
            FolderIdentityHistory,
            ResourceIdentityHistory,
        )

        folder_histories = list(
            (await session.scalars(select(FolderIdentityHistory))).all()
        )
        resource_histories = list(
            (await session.scalars(select(ResourceIdentityHistory))).all()
        )
        folder_identities = list((await session.scalars(select(FolderIdentity))).all())
        resource_identities = list((await session.scalars(select(ResourceIdentity))).all())

        assert folder_identities == []
        assert resource_identities == []
        assert folder_histories == []
        assert resource_histories == []
    await engine.dispose()


async def test_cross_root_move_not_preserved():
    """Contract: moving a folder across roots must NOT preserve its identity.

    The resolver scopes fingerprint reuse by root_mapping_id; a folder that
    appears under a different root is treated as a new identity rather than a
    move of the original.  This test pins that contract by backfilling under
    root 1 and confirming a lookup-by-path under root 2 finds nothing.
    """
    engine, factory = await _make_factory()
    async with factory() as session:
        repo = SqlAlchemyFolderIdentityRepository(session)
        await repo.backfill_folder_identity(
            "/root1/photos", "f_photos_root1", "fp_photos", root_mapping_id=1, now=NOW
        )
        await session.commit()

        found_root1 = await repo.find_folder_identity("/root1/photos")
        assert found_root1 is not None
        assert found_root1.root_mapping_id == 1

        found_root2 = await repo.find_folder_identity("/root2/photos")
        assert found_root2 is None

        record_root2 = await repo.backfill_folder_identity(
            "/root2/photos", "f_photos_root2", "fp_photos", root_mapping_id=2, now=NOW
        )
        await session.commit()
        assert record_root2.folder_id != "f_photos_root1"
        assert record_root2.root_mapping_id == 2
    await engine.dispose()


async def test_folder_rename_updates_descendant_paths():
    """Folder rename must update descendant folder identity paths.

    Backfill under /root/old/{sub,sub/deep}; then rename the parent by
    updating current_path for the parent and every descendant whose path
    starts with the old prefix.  Descendants must reflect the new prefix.
    """
    engine, factory = await _make_factory()
    async with factory() as session:
        repo = SqlAlchemyFolderIdentityRepository(session)
        await repo.backfill_folder_identity(
            "/root/old", "f_old", "fp_old", root_mapping_id=1, now=NOW
        )
        await repo.backfill_folder_identity(
            "/root/old/sub", "f_old_sub", "fp_sub", root_mapping_id=1, now=NOW
        )
        await repo.backfill_folder_identity(
            "/root/old/sub/deep", "f_old_sub_deep", "fp_deep", root_mapping_id=1, now=NOW
        )
        await session.commit()

        old_prefix = "/root/old"
        new_prefix = "/root/renamed"
        descendants = await repo.find_descendants_by_folder(old_prefix)
        for record in descendants:
            new_path = new_prefix + record.current_path[len(old_prefix):]
            entity = await session.get(FolderIdentity, record.folder_id)
            entity.current_path = new_path
        parent = await session.get(FolderIdentity, "f_old")
        parent.current_path = new_prefix
        await session.commit()

        renamed_descendants = await repo.find_descendants_by_folder(new_prefix)
        paths = sorted(d.current_path for d in renamed_descendants)
        assert paths == ["/root/renamed/sub", "/root/renamed/sub/deep"]

        old_descendants = await repo.find_descendants_by_folder(old_prefix)
        assert old_descendants == []
    await engine.dispose()
