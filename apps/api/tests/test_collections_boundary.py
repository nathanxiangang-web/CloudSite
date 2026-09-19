"""Collections module ownership and vertical application boundary regression."""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.models import (
    Collection as LegacyCollection,
    CollectionItem as LegacyCollectionItem,
)
from cloudsite.modules.catalog.infrastructure.models import CatalogEntry
from cloudsite.modules.collections.contracts.public import (
    CollectionNotFound,
    create_collection,
    delete_collection,
    get_admin_collection,
    get_public_collection,
    replace_collection_items,
    update_collection,
)
from cloudsite.modules.collections.infrastructure.models import (
    Collection,
    CollectionItem,
)
from cloudsite.modules.providers.infrastructure.models import ContentRootMapping
from cloudsite.modules.resources.infrastructure.models import Resource
from cloudsite.platform.db import IndexBase, StateBase


def test_legacy_collection_exports_are_exact_module_classes():
    assert LegacyCollection is Collection
    assert LegacyCollectionItem is CollectionItem
    assert Collection.__module__ == (
        "cloudsite.modules.collections.infrastructure.models"
    )
    assert CollectionItem.__module__ == (
        "cloudsite.modules.collections.infrastructure.models"
    )


async def test_collections_application_boundary_mixed_items():
    state_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    index_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    index_factory = async_sessionmaker(index_engine, expire_on_commit=False)

    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)

    async with state_factory() as state:
        state.add(
            ContentRootMapping(
                id=1,
                content_type="software",
                display_name="Public",
                alist_path="/public",
                enabled=True,
            )
        )
        state.add(
            CatalogEntry(
                entry_id="ce-1",
                content_type="software",
                slug="entry-one",
                title="Entry One",
                summary="summary",
                status="published",
                revision=1,
            )
        )
        await state.commit()

    async with index_factory() as index:
        index.add(
            Resource(
                id="res-1",
                name="file.zip",
                path="/public/file.zip",
                content_type="software",
                root_mapping_id=1,
                extension="zip",
                mime_type="application/zip",
                size=42,
                status="active",
            )
        )
        await index.commit()

    async with state_factory() as state:
        collection_id = await create_collection(
            state,
            values={
                "name": "Mixed",
                "description": "",
                "cover": "",
                "status": "active",
                "visible_on_home": True,
                "sort_order": 0,
                "goal": "",
                "audience": "",
                "prerequisites": "",
                "item_intro": "",
            },
        )

    async with state_factory() as state, index_factory() as index:
        count = await replace_collection_items(
            state,
            index,
            collection_id,
            items=[
                {
                    "item_type": "resource",
                    "resource_id": "res-1",
                    "note": "resource note",
                },
                {
                    "item_type": "catalog_entry",
                    "catalog_entry_id": "ce-1",
                    "note": "catalog note",
                },
            ],
            resource_ids=[],
        )
        assert count == 2

        public = await get_public_collection(
            state,
            index,
            collection_id,
        )
        assert public["item_count"] == 2
        assert [item["item_type"] for item in public["items"]] == [
            "resource",
            "catalog_entry",
        ]

        admin = await get_admin_collection(
            state,
            index,
            collection_id,
        )
        assert len(admin["items"]) == 2
        assert all(item["active"] is True for item in admin["items"])

    async with state_factory() as state:
        await update_collection(
            state,
            collection_id,
            values={"name": "Mixed Updated"},
        )

    async with state_factory() as state, index_factory() as index:
        updated = await get_admin_collection(state, index, collection_id)
        assert updated["name"] == "Mixed Updated"

    async with state_factory() as state:
        await delete_collection(state, collection_id)

    async with state_factory() as state, index_factory() as index:
        try:
            await get_public_collection(state, index, collection_id)
        except CollectionNotFound:
            pass
        else:
            raise AssertionError("deleted collection must not remain readable")

    await state_engine.dispose()
    await index_engine.dispose()
