"""Cross-module regression for the primary content delivery flow."""

from types import SimpleNamespace

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.modules.indexing.infrastructure.alist_adapter import AListProviderAdapter
from cloudsite.modules.indexing.infrastructure.legacy_bridge import run_indexing_v2
from cloudsite.modules.indexing.infrastructure.production_store import ProductionIndexingStore
from cloudsite.modules.resources.api.queries import resource_queries
from cloudsite.modules.resources.infrastructure.inventory_repository import (
    SqlAlchemyResourceInventoryRepository,
)
from cloudsite.modules.search.contracts.public import (
    rebuild_public_search_index,
    search_public_resources,
)
from cloudsite.platform.db import IndexBase, StateBase


class _FakeAListClient:
    async def list_path(self, path: str):
        if path == "/":
            return [
                {"name": "docs", "is_dir": True},
                {
                    "name": "app.zip",
                    "is_dir": False,
                    "size": 100,
                    "modified": "2026-09-20T00:00:00Z",
                },
            ]
        if path == "/docs":
            return [
                {
                    "name": "guide.pdf",
                    "is_dir": False,
                    "size": 200,
                    "modified": "2026-09-20T01:00:00Z",
                }
            ]
        return []

    async def get_file_info(self, path: str):
        return {"name": path.rsplit("/", 1)[-1]}


async def _stores():
    state_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    index_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    index_factory = async_sessionmaker(index_engine, expire_on_commit=False)

    async with state_engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as connection:
        await connection.run_sync(IndexBase.metadata.create_all)
        await connection.execute(
            text(
                "CREATE VIRTUAL TABLE search_fts USING fts5("
                "object_id UNINDEXED, object_type UNINDEXED, name, extension, "
                "content_type UNINDEXED, description, tags, breadcrumb_text)"
            )
        )

    return state_engine, index_engine, state_factory, index_factory


async def test_indexed_alist_content_flows_through_browse_search_and_download():
    state_engine, index_engine, state_factory, index_factory = await _stores()
    try:
        root = SimpleNamespace(
            id=1,
            content_type="file",
            alist_path="/",
            display_name="全部内容",
        )
        adapter = AListProviderAdapter(_FakeAListClient(), [root])

        async with index_factory() as index:
            inventory = SqlAlchemyResourceInventoryRepository(index)
            store = ProductionIndexingStore(inventory)
            result = await run_indexing_v2(
                adapter=adapter,
                store=store,
                category_ids=["root:1"],
            )
            await index.commit()

            assert result["status"] == "success"
            assert result["writes"]["added"] == 4

            queries = resource_queries(index)
            browsed = await queries.browse_resources(
                enabled_root_ids={1},
                status="active",
                content_type=None,
                page=1,
                page_size=24,
                sort="name",
                order="asc",
            )
            assert browsed.total == 2
            assert {item.name for item in browsed.items} == {
                "app.zip",
                "guide.pdf",
            }

            folders = await queries.list_folders(
                enabled_root_ids={1},
                content_type=None,
                parent_id=None,
                parent_filter_supplied=False,
            )
            by_name = {item.name: item for item in folders}
            assert by_name["全部内容"].depth == 0
            assert by_name["全部内容"].child_folder_count == 1
            assert by_name["全部内容"].resource_count == 1
            assert by_name["docs"].depth == 1
            assert by_name["docs"].resource_count == 1

            async with state_factory() as state:
                rebuilt = await rebuild_public_search_index(state, index)
                assert rebuilt.resources == 2
                assert rebuilt.folders == 2

            searched = await search_public_resources(
                index,
                query="guide",
                resource_type=None,
                object_type="all",
                page=1,
                page_size=24,
                sort="relevance",
                enabled_root_ids={1},
            )
            assert searched["total"] == 1
            assert searched["items"][0]["name"] == "guide.pdf"

            guide_id = searched["items"][0]["id"]
            download = await queries.download_resource(
                resource_id=guide_id,
                enabled_root_ids={1},
            )
            assert download.path == "/docs/guide.pdf"
            assert download.root_mapping_id == 1
    finally:
        await state_engine.dispose()
        await index_engine.dispose()
