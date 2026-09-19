"""Collection items must stay inside enabled publication roots."""

from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.database import IndexBase, StateBase
from cloudsite.models import Collection, CollectionItem, ContentRootMapping, Resource
from cloudsite.modules.collections.contracts.public import collection_view


async def _store():
    state_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    index_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    index_factory = async_sessionmaker(index_engine, expire_on_commit=False)
    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)

    async with state_factory() as state:
        state.add_all(
            [
                ContentRootMapping(id=1, content_type="software", display_name="enabled", alist_path="/enabled", enabled=True),
                ContentRootMapping(id=2, content_type="software", display_name="disabled", alist_path="/disabled", enabled=False),
                Collection(id=10, name="Mixed", description="", cover="", status="active", visible_on_home=True, sort_order=0),
                Collection(id=11, name="Only disabled", description="", cover="", status="active", visible_on_home=True, sort_order=1),
                CollectionItem(id=1, collection_id=10, resource_id="a_one", sort_order=0),
                CollectionItem(id=2, collection_id=10, resource_id="b_one", sort_order=1),
                CollectionItem(id=3, collection_id=10, resource_id="a_two", sort_order=2),
                CollectionItem(id=4, collection_id=11, resource_id="b_two", sort_order=0),
            ]
        )
        await state.commit()

    async with index_factory() as index:
        for resource_id, name, path, root_id in (
            ("a_one", "one.zip", "/enabled/one.zip", 1),
            ("a_two", "two.zip", "/enabled/two.zip", 1),
            ("b_one", "one.zip", "/disabled/one.zip", 2),
            ("b_two", "two.zip", "/disabled/two.zip", 2),
        ):
            index.add(
                Resource(
                    id=resource_id,
                    name=name,
                    path=path,
                    parent_id=None,
                    content_type="software",
                    root_mapping_id=root_id,
                    extension="zip",
                    mime_type="application/zip",
                    size=100,
                    thumbnail="",
                    status="active",
                )
            )
        await index.commit()

    return state_engine, index_engine, state_factory, index_factory


async def test_collection_filters_disabled_roots_and_preserves_order():
    state_engine, index_engine, state_factory, index_factory = await _store()
    async with state_factory() as state, index_factory() as index:
        collection = await state.get(Collection, 10)
        payload = await collection_view(state, index, collection, include_items=True)
    assert [item["id"] for item in payload["items"]] == ["a_one", "a_two"]
    assert payload["item_count"] == 2
    await state_engine.dispose()
    await index_engine.dispose()


async def test_collection_with_only_disabled_items_remains_empty_and_present():
    state_engine, index_engine, state_factory, index_factory = await _store()
    async with state_factory() as state, index_factory() as index:
        collection = await state.get(Collection, 11)
        payload = await collection_view(state, index, collection, include_items=True)
    assert payload["id"] == 11
    assert payload["items"] == []
    assert payload["item_count"] == 0
    await state_engine.dispose()
    await index_engine.dispose()


async def test_reenabling_root_restores_collection_items_without_rewrite():
    state_engine, index_engine, state_factory, index_factory = await _store()
    async with state_factory() as state:
        await state.execute(update(ContentRootMapping).where(ContentRootMapping.id == 2).values(enabled=True))
        await state.commit()
    async with state_factory() as state, index_factory() as index:
        collection = await state.get(Collection, 10)
        payload = await collection_view(state, index, collection, include_items=True)
    assert [item["id"] for item in payload["items"]] == ["a_one", "b_one", "a_two"]
    assert payload["item_count"] == 3
    await state_engine.dispose()
    await index_engine.dispose()


async def _store_both_enabled():
    """两个 enabled root，collection 跨 root 包含资源，用于预热后禁用回归。"""
    state_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    index_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    index_factory = async_sessionmaker(index_engine, expire_on_commit=False)
    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)

    async with state_factory() as state:
        state.add_all(
            [
                ContentRootMapping(id=1, content_type="software", display_name="root-a", alist_path="/root-a", enabled=True),
                ContentRootMapping(id=2, content_type="software", display_name="root-b", alist_path="/root-b", enabled=True),
                Collection(id=20, name="Cross root", description="", cover="", status="active", visible_on_home=True, sort_order=0),
                CollectionItem(id=10, collection_id=20, resource_id="x_one", sort_order=0),
                CollectionItem(id=11, collection_id=20, resource_id="y_one", sort_order=1),
            ]
        )
        await state.commit()

    async with index_factory() as index:
        for resource_id, name, path, root_id in (
            ("x_one", "alpha.zip", "/root-a/alpha.zip", 1),
            ("y_one", "beta.zip", "/root-b/beta.zip", 2),
        ):
            index.add(
                Resource(
                    id=resource_id,
                    name=name,
                    path=path,
                    parent_id=None,
                    content_type="software",
                    root_mapping_id=root_id,
                    extension="zip",
                    mime_type="application/zip",
                    size=100,
                    thumbnail="",
                    status="active",
                )
            )
        await index.commit()

    return state_engine, index_engine, state_factory, index_factory


async def test_preload_then_disable_root_hides_items():
    """预热 collection 后禁用 root，再次查询不继续展示禁用 root 的资源。"""
    state_engine, index_engine, state_factory, index_factory = await _store_both_enabled()
    async with state_factory() as state, index_factory() as index:
        collection = await state.get(Collection, 20)
        payload = await collection_view(state, index, collection, include_items=True)
        assert {item["id"] for item in payload["items"]} == {"x_one", "y_one"}
    async with state_factory() as state:
        await state.execute(
            update(ContentRootMapping).where(ContentRootMapping.id == 2).values(enabled=False)
        )
        await state.commit()
    async with state_factory() as state, index_factory() as index:
        collection = await state.get(Collection, 20)
        payload = await collection_view(state, index, collection, include_items=True)
        assert [item["id"] for item in payload["items"]] == ["x_one"]
        assert payload["item_count"] == 1
    await state_engine.dispose()
    await index_engine.dispose()


async def test_cross_root_same_parent_collection_items_do_not_mix():
    """跨 root 同 parent_id 的资源在 collection 中不混入禁用 root 的项。"""
    state_engine, index_engine, state_factory, index_factory = await _store_both_enabled()
    async with state_factory() as state:
        await state.execute(
            update(ContentRootMapping).where(ContentRootMapping.id == 2).values(enabled=False)
        )
        await state.commit()
    async with state_factory() as state, index_factory() as index:
        collection = await state.get(Collection, 20)
        payload = await collection_view(state, index, collection, include_items=True)
        item_ids = {item["id"] for item in payload["items"]}
        assert "y_one" not in item_ids
        assert item_ids == {"x_one"}
    await state_engine.dispose()
    await index_engine.dispose()
