"""Catalog-owned search projection outbox write side."""

from __future__ import annotations

import secrets

from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure.models import CatalogSearchOutbox


OUTBOX_ID_PREFIX = "cso_"
_ID_HEX_LEN = 32


def _new_outbox_id() -> str:
    return OUTBOX_ID_PREFIX + secrets.token_hex(_ID_HEX_LEN // 2)


async def enqueue_catalog_search_outbox(
    state: AsyncSession,
    *,
    entry_id: str,
    revision: int,
    action: str = "upsert",
) -> None:
    if action not in {"upsert", "delete"}:
        raise ValueError(f"unsupported outbox action: {action}")
    state.add(
        CatalogSearchOutbox(
            outbox_id=_new_outbox_id(),
            entry_id=entry_id,
            revision=revision,
            action=action,
        )
    )
    await state.flush()


__all__ = ["enqueue_catalog_search_outbox"]
