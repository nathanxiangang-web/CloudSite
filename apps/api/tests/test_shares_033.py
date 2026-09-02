from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.database import IndexBase, StateBase
from cloudsite.models import Collection, CollectionItem, ContentRootMapping, Folder, Resource, Share, utcnow
from cloudsite.schemas import ShareInput
from cloudsite.shares.code import SHARE_CODE_ALPHABET, verify_share_code
from cloudsite.shares.service import (
    MAX_SHARE_DOWNLOADS,
    collection_in_publication_scope,
    create_share,
    reserve_share_download,
    share_expires_at,
    share_status,
)


async def share_store():
    state_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    index_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    index_factory = async_sessionmaker(index_engine, expire_on_commit=False)
    async with state_engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as connection:
        await connection.run_sync(IndexBase.metadata.create_all)
    return state_engine, index_engine, state_factory, index_factory


async def seed_resource(state_factory, index_factory):
    async with state_factory() as state:
        state.add(ContentRootMapping(id=1, content_type="file", display_name="文件", alist_path="/", enabled=True))
        await state.commit()
    async with index_factory() as index:
        index.add(Resource(id="r_share", name="share.bin", path="/share.bin", parent_id=None, content_type="file", root_mapping_id=1, extension="bin", mime_type="application/octet-stream", size=8, thumbnail="", status="active"))
        await index.commit()


@pytest.mark.parametrize("duration", ["5m", "1h", "6h", "24h", "7d"])
def test_share_duration_options(duration):
    now = utcnow()
    assert share_expires_at(duration, now) > now
    assert share_expires_at("permanent", now) is None


async def test_code_share_generates_four_character_hashed_code():
    state_engine, index_engine, state_factory, index_factory = await share_store()
    await seed_resource(state_factory, index_factory)
    async with state_factory() as state, index_factory() as index:
        created = await create_share(state, index, ShareInput(object_type="resource", object_id="r_share", access_mode="code", duration="1h"))
        await state.commit()
        assert created.code is not None
        assert len(created.code) == 4
        assert set(created.code) <= set(SHARE_CODE_ALPHABET)
        assert created.share.code_hash != created.code
        assert verify_share_code(created.share.token, created.code.lower(), created.share.code_hash)
    await state_engine.dispose()
    await index_engine.dispose()


async def test_direct_share_resource_only_and_has_no_code():
    state_engine, index_engine, state_factory, index_factory = await share_store()
    await seed_resource(state_factory, index_factory)
    async with state_factory() as state, index_factory() as index:
        created = await create_share(state, index, ShareInput(object_type="resource", object_id="r_share", access_mode="direct", duration="24h"))
        await state.commit()
        assert created.code is None
        assert created.share.code_hash is None
        assert created.share.code_version == 0
        with pytest.raises(Exception):
            await create_share(state, index, ShareInput(object_type="folder", object_id="f_share", access_mode="direct", duration="24h"))
    await state_engine.dispose()
    await index_engine.dispose()


async def test_legacy_code_share_without_hash_is_migration_pending():
    row = Share(token="legacy", object_type="resource", object_id="r_share", enabled=True, access_mode="code", code_hash=None)
    assert share_status(row, target_valid=True) == "migration_pending"


async def test_collection_share_rejects_missing_resources():
    state_engine, index_engine, state_factory, index_factory = await share_store()
    await seed_resource(state_factory, index_factory)
    async with state_factory() as state:
        collection = Collection(name="测试合集", status="active")
        state.add(collection)
        await state.flush()
        state.add_all(
            [
                CollectionItem(collection_id=collection.id, resource_id="r_share"),
                CollectionItem(collection_id=collection.id, resource_id="r_missing"),
            ]
        )
        await state.commit()
        async with index_factory() as index:
            assert not await collection_in_publication_scope(state, index, collection)
    await state_engine.dispose()
    await index_engine.dispose()


async def test_expired_cancelled_and_invalid_target_status_priority():
    old = utcnow() - timedelta(minutes=1)
    assert share_status(Share(token="x", object_type="resource", object_id="r", access_mode="direct", enabled=False, expires_at=old), True) == "cancelled"
    assert share_status(Share(token="x", object_type="resource", object_id="r", access_mode="direct", enabled=True, expires_at=old), True) == "expired"
    assert share_status(Share(token="x", object_type="resource", object_id="r", access_mode="direct", enabled=True), False) == "invalid_target"


async def test_atomic_download_reservation_stops_at_404():
    state_engine, _, state_factory, _ = await share_store()
    async with state_factory() as state:
        state.add(Share(token="limit", object_type="resource", object_id="r_share", enabled=True, access_mode="direct", download_count=403))
        await state.commit()
        assert await reserve_share_download(state, "limit") == MAX_SHARE_DOWNLOADS
        await state.commit()
        row = await state.get(Share, "limit")
        assert row is not None
        assert row.download_count == MAX_SHARE_DOWNLOADS
        assert row.enabled is False
        assert row.cancel_reason == "download_limit"
        with pytest.raises(Exception):
            await reserve_share_download(state, "limit")
        await state.rollback()
        assert (await state.scalar(select(Share.download_count).where(Share.token == "limit"))) == MAX_SHARE_DOWNLOADS
    await state_engine.dispose()
