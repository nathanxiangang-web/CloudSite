"""8.3 单元测试：FolderIdentity 解析与改名检测"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.database import StateBase
from cloudsite.identity.fingerprint import folder_identity_fingerprint
from cloudsite.identity.schemas import FolderIdentityObservation
from cloudsite.identity.service import resolve_folder_identities, cascade_rename_descendants
from cloudsite.models import Folder, FolderIdentity, FolderIdentityHistory, Resource


async def _make_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    return engine, factory


def test_folder_fingerprint_stable_for_same_entries():
    entries = [{"name": "a", "is_dir": True}, {"name": "b.txt", "is_dir": False}]
    assert folder_identity_fingerprint(entries) == folder_identity_fingerprint(entries)


def test_folder_fingerprint_changes_with_different_entries():
    a = [{"name": "a", "is_dir": True}]
    b = [{"name": "b", "is_dir": True}]
    assert folder_identity_fingerprint(a) != folder_identity_fingerprint(b)


def test_folder_fingerprint_order_independent():
    entries_a = [{"name": "a", "is_dir": True}, {"name": "b", "is_dir": False}]
    entries_b = [{"name": "b", "is_dir": False}, {"name": "a", "is_dir": True}]
    assert folder_identity_fingerprint(entries_a) == folder_identity_fingerprint(entries_b)


async def test_resolve_new_folder_creates_identity():
    engine, factory = await _make_factory()
    now = datetime(2026, 9, 6, tzinfo=timezone.utc)
    fp = folder_identity_fingerprint([{"name": "child", "is_dir": False}])
    obs = FolderIdentityObservation(path="/root/newdir", name="newdir", root_mapping_id=1, fingerprint=fp)

    async with factory() as session:
        resolutions = await resolve_folder_identities(session, [obs], visible_paths={"/root/newdir"}, now=now)
        assert len(resolutions) == 1
        assert resolutions[0].match_type == "created"
        assert resolutions[0].folder_id.startswith("f_")

        identities = list((await session.scalars(select(FolderIdentity))).all())
        assert len(identities) == 1
        assert identities[0].current_path == "/root/newdir"
        assert identities[0].status == "active"
    await engine.dispose()


async def test_resolve_observed_existing_path():
    engine, factory = await _make_factory()
    now = datetime(2026, 9, 6, tzinfo=timezone.utc)
    fp = folder_identity_fingerprint([{"name": "child", "is_dir": False}])

    async with factory() as session:
        session.add(FolderIdentity(
            folder_id="f_existing", current_path="/root/dir", root_mapping_id=1,
            status="active", last_name="dir", identity_fingerprint=fp,
            created_from="new_folder", first_seen_at=now, last_seen_at=now,
        ))
        await session.commit()

        obs = FolderIdentityObservation(path="/root/dir", name="dir", root_mapping_id=1, fingerprint=fp)
        resolutions = await resolve_folder_identities(session, [obs], visible_paths={"/root/dir"}, now=now)
        assert resolutions[0].match_type == "observed"
        assert resolutions[0].folder_id == "f_existing"
    await engine.dispose()


async def test_resolve_renamed_via_fingerprint_match():
    engine, factory = await _make_factory()
    now = datetime(2026, 9, 6, tzinfo=timezone.utc)
    fp = folder_identity_fingerprint([{"name": "child", "is_dir": False}])

    async with factory() as session:
        session.add(FolderIdentity(
            folder_id="f_old", current_path="/root/oldname", root_mapping_id=1,
            status="active", last_name="oldname", identity_fingerprint=fp,
            created_from="new_folder", first_seen_at=now, last_seen_at=now,
        ))
        await session.commit()

        obs = FolderIdentityObservation(path="/root/newname", name="newname", root_mapping_id=1, fingerprint=fp)
        resolutions = await resolve_folder_identities(session, [obs], visible_paths={"/root/newname"}, now=now)
        assert resolutions[0].match_type == "rename"
        assert resolutions[0].folder_id == "f_old"
        assert resolutions[0].previous_path == "/root/oldname"

        identity = await session.get(FolderIdentity, "f_old")
        assert identity.current_path == "/root/newname"

        histories = list((await session.scalars(select(FolderIdentityHistory))).all())
        assert len(histories) == 1
        assert histories[0].event_type == "rename"
    await engine.dispose()


async def test_resolve_reactivated_from_suspected_missing():
    engine, factory = await _make_factory()
    now = datetime(2026, 9, 6, tzinfo=timezone.utc)
    fp = folder_identity_fingerprint([{"name": "child", "is_dir": False}])

    async with factory() as session:
        session.add(FolderIdentity(
            folder_id="f_missing", current_path="/root/dir", root_mapping_id=1,
            status="suspected_missing", last_name="dir", identity_fingerprint=fp,
            created_from="new_folder", first_seen_at=now, last_seen_at=now,
        ))
        await session.commit()

        obs = FolderIdentityObservation(path="/root/dir", name="dir", root_mapping_id=1, fingerprint=fp)
        resolutions = await resolve_folder_identities(session, [obs], visible_paths={"/root/dir"}, now=now)
        assert resolutions[0].match_type == "reactivated"
    await engine.dispose()


async def test_cascade_rename_descendants_updates_paths():
    from cloudsite.database import IndexBase
    index_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    index_factory = async_sessionmaker(index_engine, expire_on_commit=False)
    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)

    now = datetime(2026, 9, 6, tzinfo=timezone.utc)
    async with index_factory() as session:
        session.add(Folder(id="f1", name="foo", path="/root/foo", parent_id=None, content_type="software", root_mapping_id=1, status="active"))
        session.add(Folder(id="f2", name="sub", path="/root/foo/sub", parent_id="f1", content_type="software", root_mapping_id=1, status="active"))
        session.add(Resource(id="r1", name="file.txt", path="/root/foo/sub/file.txt", parent_id="f2", content_type="software", root_mapping_id=1, status="active", size=100, extension="txt"))
        await session.commit()

        result = await cascade_rename_descendants(session, "f1", "/root/foo", "/root/bar")
        assert result["folders_updated"] >= 1
        assert result["resources_updated"] >= 1

        folders = list((await session.scalars(select(Folder).where(Folder.path.like("/root/bar%")))).all())
        assert any(f.path == "/root/bar/sub" for f in folders)
        resources = list((await session.scalars(select(Resource).where(Resource.path.like("/root/bar%")))).all())
        assert any(r.path == "/root/bar/sub/file.txt" for r in resources)
    await index_engine.dispose()


async def test_cascade_rename_escapes_wildcards_and_only_replaces_leading_prefix():
    from cloudsite.database import IndexBase
    index_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    index_factory = async_sessionmaker(index_engine, expire_on_commit=False)
    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)
    async with index_factory() as session:
        session.add(Folder(id="fa", name="a", path="/a", parent_id=None, content_type="software", root_mapping_id=1, status="active"))
        session.add(Folder(id="fab", name="b", path="/a/b", parent_id="fa", content_type="software", root_mapping_id=1, status="active"))
        session.add(Folder(id="faub", name="a_b", path="/a_b", parent_id=None, content_type="software", root_mapping_id=1, status="active"))
        session.add(Folder(id="faubc", name="c", path="/a_b/c", parent_id="faub", content_type="software", root_mapping_id=1, status="active"))
        session.add(Folder(id="fapct", name="a%", path="/a%", parent_id=None, content_type="software", root_mapping_id=1, status="active"))
        session.add(Folder(id="fapctd", name="d", path="/a%/d", parent_id="fapct", content_type="software", root_mapping_id=1, status="active"))
        session.add(Folder(id="fx", name="x", path="/x", parent_id=None, content_type="software", root_mapping_id=1, status="active"))
        session.add(Folder(id="fxae", name="a", path="/x/a", parent_id="fx", content_type="software", root_mapping_id=1, status="active"))
        session.add(Folder(id="fxaef", name="e", path="/x/a/e", parent_id="fxae", content_type="software", root_mapping_id=1, status="active"))
        await session.commit()

        result = await cascade_rename_descendants(session, "fa", "/a", "/renamed")
        assert result["folders_updated"] == 1
        await session.commit()
        paths = sorted(f.path for f in (await session.scalars(select(Folder))).all())
        assert "/renamed/b" in paths
        assert "/a/b" not in paths
        assert "/a_b/c" in paths
        assert "/a%/d" in paths
        assert "/x/a/e" in paths
        assert "/x/a" in paths
    await index_engine.dispose()


async def test_cascade_rename_escapes_underscore_in_old_prefix():
    from cloudsite.database import IndexBase
    index_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    index_factory = async_sessionmaker(index_engine, expire_on_commit=False)
    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)
    async with index_factory() as session:
        session.add(Folder(id="fab", name="a_b", path="/a_b", parent_id=None, content_type="software", root_mapping_id=1, status="active"))
        session.add(Folder(id="fabx", name="x", path="/a_b/x", parent_id="fab", content_type="software", root_mapping_id=1, status="active"))
        session.add(Folder(id="faxb", name="axb", path="/axb", parent_id=None, content_type="software", root_mapping_id=1, status="active"))
        session.add(Folder(id="faxby", name="y", path="/axb/y", parent_id="faxb", content_type="software", root_mapping_id=1, status="active"))
        await session.commit()

        result = await cascade_rename_descendants(session, "fab", "/a_b", "/new")
        assert result["folders_updated"] == 1
        await session.commit()
        paths = sorted(f.path for f in (await session.scalars(select(Folder))).all())
        assert "/new/x" in paths
        assert "/axb/y" in paths
    await index_engine.dispose()

async def test_resolve_empty_fingerprint_does_not_match_and_creates_new():
    engine, factory = await _make_factory()
    now = datetime(2026, 9, 6, tzinfo=timezone.utc)
    async with factory() as session:
        session.add(FolderIdentity(
            folder_id="f_old", current_path="/root/oldname", root_mapping_id=1,
            status="active", last_name="oldname", identity_fingerprint="somefp",
            created_from="new_folder", first_seen_at=now, last_seen_at=now,
        ))
        await session.commit()
        obs = FolderIdentityObservation(path="/root/newname", name="newname", root_mapping_id=1, fingerprint="")
        resolutions = await resolve_folder_identities(session, [obs], visible_paths={"/root/newname"}, now=now)
        assert resolutions[0].match_type == "created"
        assert resolutions[0].folder_id != "f_old"
    await engine.dispose()


async def test_resolve_cross_root_does_not_match_and_creates_new():
    engine, factory = await _make_factory()
    now = datetime(2026, 9, 6, tzinfo=timezone.utc)
    fp = folder_identity_fingerprint([{"name": "child", "is_dir": False}])
    async with factory() as session:
        session.add(FolderIdentity(
            folder_id="f_old", current_path="/root/oldname", root_mapping_id=1,
            status="active", last_name="oldname", identity_fingerprint=fp,
            created_from="new_folder", first_seen_at=now, last_seen_at=now,
        ))
        await session.commit()
        obs = FolderIdentityObservation(path="/other/newname", name="newname", root_mapping_id=2, fingerprint=fp)
        resolutions = await resolve_folder_identities(session, [obs], visible_paths={"/other/newname"}, now=now)
        assert resolutions[0].match_type == "created"
        assert resolutions[0].folder_id != "f_old"
    await engine.dispose()


async def test_resolve_multiple_candidates_ambiguous_creates_new():
    engine, factory = await _make_factory()
    now = datetime(2026, 9, 6, tzinfo=timezone.utc)
    fp = folder_identity_fingerprint([{"name": "child", "is_dir": False}])
    async with factory() as session:
        session.add(FolderIdentity(
            folder_id="f_a", current_path="/root/a", root_mapping_id=1,
            status="active", last_name="a", identity_fingerprint=fp,
            created_from="new_folder", first_seen_at=now, last_seen_at=now,
        ))
        session.add(FolderIdentity(
            folder_id="f_b", current_path="/root/b", root_mapping_id=1,
            status="active", last_name="b", identity_fingerprint=fp,
            created_from="new_folder", first_seen_at=now, last_seen_at=now,
        ))
        await session.commit()
        obs = FolderIdentityObservation(path="/root/c", name="c", root_mapping_id=1, fingerprint=fp)
        resolutions = await resolve_folder_identities(session, [obs], visible_paths={"/root/c"}, now=now)
        assert resolutions[0].match_type == "ambiguous"
        assert resolutions[0].folder_id not in ("f_a", "f_b")
    await engine.dispose()


async def test_resolve_does_not_commit_internally():
    engine, factory = await _make_factory()
    now = datetime(2026, 9, 6, tzinfo=timezone.utc)
    fp = folder_identity_fingerprint([{"name": "child", "is_dir": False}])
    async with factory() as session:
        obs = FolderIdentityObservation(path="/root/newdir", name="newdir", root_mapping_id=1, fingerprint=fp)
        await resolve_folder_identities(session, [obs], visible_paths={"/root/newdir"}, now=now)
    async with factory() as session:
        identities = list((await session.scalars(select(FolderIdentity))).all())
        assert len(identities) == 0
    await engine.dispose()
