"""Cross-module orchestration for provider root lifecycle."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..modules.identity.contracts.public import cascade_delete_root_identities
from ..modules.providers.contracts.public import delete_root_mapping


async def delete_root_mapping_with_identity_cleanup(
    state: AsyncSession,
    mapping_id: int,
) -> dict[str, int]:
    """Delete Identity-owned rows, then delete the provider root atomically.

    Identity cleanup only flushes. Providers performs the final commit when
    deleting the root mapping, so both module changes share one transaction.
    """
    deleted = await cascade_delete_root_identities(state, mapping_id)
    await delete_root_mapping(state, mapping_id)
    return deleted


__all__ = ["delete_root_mapping_with_identity_cleanup"]
