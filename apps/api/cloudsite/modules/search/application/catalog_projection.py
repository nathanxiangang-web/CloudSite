"""Application orchestration for the Catalog -> Search projection."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...catalog.contracts.public import (
    catalog_search_projection_source,
    mark_catalog_search_outbox_consumed,
    pending_catalog_search_outbox,
    prepare_catalog_search_rebuild,
)
from ..infrastructure.catalog_projection import (
    catalog_projection_revision,
    catalog_search_fts_match as _catalog_search_fts_match,
    clear_catalog_search_projection,
    delete_catalog_search_document,
    set_catalog_projection_revision,
    upsert_catalog_search_document,
)


async def consume_catalog_search_outbox(
    state: AsyncSession,
    index: AsyncSession,
    *,
    batch_limit: int = 500,
) -> dict[str, int]:
    """Consume Catalog outbox rows into Search-owned projection state."""
    pending = await pending_catalog_search_outbox(
        state,
        batch_limit=batch_limit,
    )
    if not pending:
        return {"consumed": 0, "skipped": 0, "failed": 0}

    consumed = 0
    skipped = 0
    failed = 0
    consumed_at = datetime.now(timezone.utc)

    for row in pending:
        try:
            existing_revision = await catalog_projection_revision(
                index,
                entry_id=row.entry_id,
            )
            if (
                existing_revision is not None
                and existing_revision >= row.revision
            ):
                skipped += 1
                await mark_catalog_search_outbox_consumed(
                    state,
                    outbox_id=row.outbox_id,
                    consumed_at=consumed_at,
                )
                continue

            source = await catalog_search_projection_source(
                state,
                entry_id=row.entry_id,
            )
            if source.document is None:
                await delete_catalog_search_document(
                    index,
                    entry_id=row.entry_id,
                )
                await set_catalog_projection_revision(
                    index,
                    entry_id=row.entry_id,
                    revision=row.revision,
                    updated_at=consumed_at,
                )
                consumed += 1
                await mark_catalog_search_outbox_consumed(
                    state,
                    outbox_id=row.outbox_id,
                    consumed_at=consumed_at,
                )
                continue

            if (
                source.revision is not None
                and source.revision > row.revision
            ):
                skipped += 1
                await mark_catalog_search_outbox_consumed(
                    state,
                    outbox_id=row.outbox_id,
                    consumed_at=consumed_at,
                )
                continue

            if row.action == "delete":
                await delete_catalog_search_document(
                    index,
                    entry_id=row.entry_id,
                )
            else:
                await upsert_catalog_search_document(
                    index,
                    source.document,
                )
            await set_catalog_projection_revision(
                index,
                entry_id=row.entry_id,
                revision=row.revision,
                updated_at=consumed_at,
            )
            consumed += 1
            await mark_catalog_search_outbox_consumed(
                state,
                outbox_id=row.outbox_id,
                consumed_at=consumed_at,
            )
        except Exception:
            failed += 1

    await index.commit()
    await state.commit()
    return {
        "consumed": consumed,
        "skipped": skipped,
        "failed": failed,
    }


async def rebuild_catalog_search_index(
    state: AsyncSession,
    index: AsyncSession,
) -> int:
    """Rebuild Search-owned Catalog FTS through the Catalog outbox contract."""
    await clear_catalog_search_projection(index)
    await index.commit()

    await prepare_catalog_search_rebuild(
        state,
        consumed_at=datetime.now(timezone.utc),
    )
    await state.commit()

    stats = await consume_catalog_search_outbox(state, index)
    return stats["consumed"]


async def catalog_search_fts_match(
    index: AsyncSession,
    *,
    query: str,
    content_type: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    return await _catalog_search_fts_match(
        index,
        query=query,
        content_type=content_type,
        limit=limit,
    )


__all__ = [
    "catalog_search_fts_match",
    "consume_catalog_search_outbox",
    "rebuild_catalog_search_index",
]
