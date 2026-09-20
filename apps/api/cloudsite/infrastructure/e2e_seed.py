"""Opt-in deterministic data seed for browser E2E tests.

This support code is inert unless the guarded E2E HTTP route is explicitly
enabled. It seeds only CloudSite-owned SQLite state/index data; it does not
pretend an external AList provider exists.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..modules.providers.infrastructure.models import ContentRootMapping
from ..modules.resources.infrastructure.models import Resource
from ..modules.search.contracts.public import rebuild_public_search_index

E2E_ROOT_PATH = "/__cloudsite_e2e__"
E2E_RESOURCE_ID = "e2e_cloudsite_package"
E2E_RESOURCE_NAME = "cloudsite-e2e-package.zip"
E2E_RESOURCE_PATH = f"{E2E_ROOT_PATH}/{E2E_RESOURCE_NAME}"


async def seed_e2e_content(
    state: AsyncSession,
    index: AsyncSession,
) -> dict[str, object]:
    """Upsert one visible resource and rebuild public Search deterministically."""

    root = await state.scalar(
        select(ContentRootMapping).where(
            ContentRootMapping.connection_id == 1,
            ContentRootMapping.alist_path == E2E_ROOT_PATH,
        )
    )
    if root is None:
        root = ContentRootMapping(
            connection_id=1,
            content_type="software",
            display_name="E2E 测试资源",
            alist_path=E2E_ROOT_PATH,
            enabled=True,
            sort_order=999_999,
            home_order=999_999,
        )
        state.add(root)
        await state.flush()
    else:
        root.content_type = "software"
        root.display_name = "E2E 测试资源"
        root.enabled = True
        root.sort_order = 999_999
        root.home_order = 999_999

    fixed_time = datetime(2026, 9, 20, tzinfo=timezone.utc)
    resource = await index.get(Resource, E2E_RESOURCE_ID)
    if resource is None:
        resource = Resource(id=E2E_RESOURCE_ID)
        index.add(resource)

    resource.name = E2E_RESOURCE_NAME
    resource.path = E2E_RESOURCE_PATH
    resource.parent_id = None
    resource.content_type = "software"
    resource.root_mapping_id = root.id
    resource.extension = "zip"
    resource.mime_type = "application/zip"
    resource.size = 1024
    resource.modified_at = fixed_time
    resource.thumbnail = ""
    resource.metadata_json = "{}"
    resource.status = "active"
    resource.indexed_at = fixed_time
    resource.missing_streak = 0
    resource.missing_candidate_at = None
    resource.last_seen_run_id = None
    resource.missing_last_observed_cycle_id = None

    await state.commit()
    await index.commit()

    rebuilt = await rebuild_public_search_index(state, index)
    await state.commit()

    return {
        "root_mapping_id": root.id,
        "resource_id": E2E_RESOURCE_ID,
        "resource_name": E2E_RESOURCE_NAME,
        "search_query": "cloudsite-e2e-package",
        "search_indexed": rebuilt.indexed,
        "download_provider_seeded": False,
    }


__all__ = [
    "E2E_RESOURCE_ID",
    "E2E_RESOURCE_NAME",
    "E2E_ROOT_PATH",
    "seed_e2e_content",
]
