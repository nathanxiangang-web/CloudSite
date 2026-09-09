from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.database import IndexBase, StateBase
from cloudsite.models import (
    CatalogAsset,
    CatalogEntry,
    CatalogLocation,
    CatalogRelease,
    CatalogTag,
    CatalogTagAssignment,
    ContentRootMapping,
    Resource,
)
from cloudsite.services.catalog_search import search_published_catalog


async def test_catalog_search_matches_metadata_and_filters_live_scope(tmp_path):
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)
    state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    index_factory = async_sessionmaker(index_engine, expire_on_commit=False)

    async with state_factory() as state, index_factory() as index:
        state.add(
            ContentRootMapping(
                id=1,
                content_type="software",
                display_name="Public",
                alist_path="/public",
                enabled=True,
            )
        )
        state.add_all(
            [
                CatalogEntry(
                    entry_id="ce_visible",
                    content_type="software",
                    slug="toolbox",
                    title="Toolbox",
                    summary="Network operations toolkit",
                    status="published",
                ),
                CatalogEntry(
                    entry_id="ce_hidden",
                    content_type="software",
                    slug="hidden-tool",
                    title="Hidden Tool",
                    summary="Network operations toolkit",
                    status="published",
                ),
                CatalogRelease(
                    release_id="cr_visible",
                    entry_id="ce_visible",
                    slug="2.0",
                    title="2.0 Stable",
                    channel="stable",
                    status="published",
                ),
                CatalogRelease(
                    release_id="cr_hidden",
                    entry_id="ce_hidden",
                    slug="1.0",
                    title="1.0",
                    channel="stable",
                    status="published",
                ),
                CatalogAsset(
                    asset_id="ca_visible",
                    release_id="cr_visible",
                    slug="windows-arm64",
                    display_name="Toolbox ARM64",
                    platform="windows",
                    architecture="arm64",
                    package_type="portable",
                ),
                CatalogAsset(
                    asset_id="ca_hidden",
                    release_id="cr_hidden",
                    slug="windows-arm64",
                    display_name="Hidden ARM64",
                    platform="windows",
                    architecture="arm64",
                    package_type="portable",
                ),
                CatalogLocation(
                    location_id="cl_visible",
                    asset_id="ca_visible",
                    resource_id="res-visible",
                    root_mapping_id=1,
                    status="active",
                ),
                CatalogLocation(
                    location_id="cl_hidden",
                    asset_id="ca_hidden",
                    resource_id="res-hidden",
                    root_mapping_id=2,
                    status="active",
                ),
                CatalogTag(tag_id="ct_network", slug="network", display_name="Network"),
                CatalogTagAssignment(
                    tag_id="ct_network", target_type="entry", target_id="ce_visible"
                ),
            ]
        )
        index.add_all(
            [
                Resource(
                    id="res-visible",
                    root_mapping_id=1,
                    name="toolbox.zip",
                    path="/public/toolbox.zip",
                    content_type="software",
                    status="active",
                ),
                Resource(
                    id="res-hidden",
                    root_mapping_id=2,
                    name="hidden.zip",
                    path="/hidden/hidden.zip",
                    content_type="software",
                    status="active",
                ),
            ]
        )
        await state.commit()
        await index.commit()

        result = await search_published_catalog(
            state,
            index,
            query="network",
            content_type="software",
            tag="network",
            platform="windows",
        )
        assert result["total"] == 1
        assert result["items"][0]["entry_id"] == "ce_visible"
        assert result["items"][0]["match_type"] == "metadata"

        exact = await search_published_catalog(state, index, query="Toolbox")
        assert exact["items"][0]["match_type"] == "exact"

        unavailable = await search_published_catalog(state, index, query="Hidden Tool")
        assert unavailable["total"] == 0

    await state_engine.dispose()
    await index_engine.dispose()


async def test_catalog_search_rejects_empty_query(tmp_path):
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    factory = async_sessionmaker(state_engine)
    index_factory = async_sessionmaker(index_engine)
    async with factory() as state, index_factory() as index:
        try:
            await search_published_catalog(state, index, query="   ")
        except ValueError as exc:
            assert "empty" in str(exc)
        else:
            raise AssertionError("empty Catalog query must be rejected")
    await state_engine.dispose()
    await index_engine.dispose()
