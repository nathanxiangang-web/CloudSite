"""Identity-owned cleanup operations for deleted provider roots."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure.folder_repository import SqlAlchemyFolderIdentityRepository
from ..infrastructure.resource_repository import SqlAlchemyResourceIdentityRepository


async def cascade_delete_root_identities(
    state: AsyncSession,
    root_mapping_id: int,
) -> dict[str, int]:
    """Delete all folder/resource identity state owned by one provider root.

    The caller owns the surrounding transaction. Keeping repository
    construction inside Identity prevents other business modules from
    depending on Identity infrastructure internals.
    """
    folder_repo = SqlAlchemyFolderIdentityRepository(state)
    resource_repo = SqlAlchemyResourceIdentityRepository(state)
    folders_deleted = await folder_repo.cascade_delete_by_root(root_mapping_id)
    resources_deleted = await resource_repo.cascade_delete_by_root(root_mapping_id)
    return {
        "folders": folders_deleted,
        "resources": resources_deleted,
    }


__all__ = ["cascade_delete_root_identities"]
