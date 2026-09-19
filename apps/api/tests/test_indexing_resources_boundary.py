"""Indexing adapter tests for the Resources persistence boundary."""

from datetime import datetime, timezone

from cloudsite.modules.indexing.infrastructure.production_store import (
    ProductionIndexingStore,
)
from cloudsite.modules.indexing.infrastructure.repository import IndexedEntry
from cloudsite.modules.resources.contracts.public import ResourceInventoryRecord


class FakeResourceInventory:
    def __init__(self):
        self.upserted = []
        self.removed = []
        self.touched = []

    async def list_indexed(self, *, category_id: str, provider_id: str):
        return [
            ResourceInventoryRecord(
                resource_id="r1",
                category_id=category_id,
                provider_id=provider_id,
                path="/a/file.txt",
                name="file.txt",
                size=7,
                is_dir=False,
                parent_id="f1",
                content_type=category_id,
                root_mapping_id=9,
                extension="txt",
                mime_type="text/plain",
                indexed_at=datetime(2026, 9, 19, tzinfo=timezone.utc),
            )
        ]

    async def upsert(self, records):
        self.upserted = list(records)
        return len(records)

    async def remove(self, resource_ids):
        self.removed = list(resource_ids)
        return len(resource_ids)

    async def touch_unchanged(self, resource_ids):
        self.touched = list(resource_ids)
        return len(resource_ids)

    async def cascade_descendant_paths(self, old_path_prefix, new_path_prefix):
        return {"folders_updated": 1, "resources_updated": 2}


async def test_indexing_store_adapts_resources_records_without_orm_access():
    resources = FakeResourceInventory()
    store = ProductionIndexingStore(resources)

    rows = await store.list_indexed(
        category_id="software",
        provider_id="generic_alist",
    )
    assert len(rows) == 1
    assert rows[0].resource_id == "r1"
    assert rows[0].metadata["parent_id"] == "f1"
    assert rows[0].metadata["extension"] == "txt"

    count = await store.upsert(
        [
            IndexedEntry(
                resource_id="r2",
                category_id="software",
                provider_id="generic_alist",
                path="/a/new.zip",
                name="new.zip",
                size=11,
                metadata={
                    "is_dir": False,
                    "parent_id": "f1",
                    "content_type": "software",
                    "root_mapping_id": 9,
                    "extension": "zip",
                    "mime_type": "application/zip",
                },
            )
        ]
    )
    assert count == 1
    record = resources.upserted[0]
    assert record.resource_id == "r2"
    assert record.parent_id == "f1"
    assert record.root_mapping_id == 9
    assert record.extension == "zip"

    assert await store.touch_unchanged(["r2"]) == 1
    assert resources.touched == ["r2"]
    assert await store.remove(["r2"]) == 1
    assert resources.removed == ["r2"]

    result = await store.cascade_descendant_paths("/old", "/new")
    assert result == {"folders_updated": 1, "resources_updated": 2}
