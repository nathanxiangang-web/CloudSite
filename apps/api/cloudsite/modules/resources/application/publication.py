"""Publication-scope queries owned by Resources."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...providers.contracts.public import enabled_root_ids
from ..domain.publication import (
    PublicationFolderView,
    PublicationResourceView,
)
from ..domain.views import FolderSummaryView
from ..infrastructure.models import Folder, Resource


def _resource_view(row: Resource) -> PublicationResourceView:
    return PublicationResourceView(
        id=row.id,
        name=row.name,
        path=row.path,
        parent_id=row.parent_id,
        content_type=row.content_type,
        root_mapping_id=int(row.root_mapping_id),
        extension=row.extension,
        mime_type=row.mime_type,
        size=row.size,
        modified_at=row.modified_at,
        thumbnail="",
    )


def _folder_view(row: Folder) -> FolderSummaryView:
    return FolderSummaryView(
        id=row.id,
        name=row.name,
        parent_id=row.parent_id,
        content_type=row.content_type,
        depth=row.depth,
        child_folder_count=row.child_folder_count,
        resource_count=row.resource_count,
        modified_at=row.modified_at,
    )


async def resource_publication_target(
    state: AsyncSession,
    index: AsyncSession,
    resource_id: str,
) -> PublicationResourceView | None:
    roots = await enabled_root_ids(state)
    row = await index.get(Resource, resource_id)
    if (
        row is None
        or row.status != "active"
        or row.root_mapping_id is None
        or row.root_mapping_id not in roots
    ):
        return None
    return _resource_view(row)


async def folder_publication_target(
    state: AsyncSession,
    index: AsyncSession,
    folder_id: str,
) -> PublicationFolderView | None:
    roots = await enabled_root_ids(state)
    row = await index.get(Folder, folder_id)
    if (
        row is None
        or row.status != "active"
        or row.root_mapping_id is None
        or row.root_mapping_id not in roots
    ):
        return None

    leaked_resource = await index.scalar(
        select(Resource.id)
        .where(
            Resource.parent_id == row.id,
            Resource.status == "active",
        )
        .where(
            or_(
                Resource.root_mapping_id.is_(None),
                Resource.root_mapping_id.not_in(roots),
            )
        )
        .limit(1)
    )
    if leaked_resource is not None:
        return None

    child_folders = tuple(
        (
            await index.scalars(
                select(Folder)
                .where(
                    Folder.parent_id == row.id,
                    Folder.status == "active",
                    Folder.root_mapping_id == row.root_mapping_id,
                )
                .order_by(Folder.name)
            )
        ).all()
    )
    child_resources = tuple(
        (
            await index.scalars(
                select(Resource)
                .where(
                    Resource.parent_id == row.id,
                    Resource.status == "active",
                    Resource.root_mapping_id == row.root_mapping_id,
                )
                .order_by(Resource.name)
            )
        ).all()
    )
    return PublicationFolderView(
        folder=_folder_view(row),
        root_mapping_id=int(row.root_mapping_id),
        folders=tuple(_folder_view(item) for item in child_folders),
        resources=tuple(_resource_view(item) for item in child_resources),
    )


__all__ = [
    "folder_publication_target",
    "resource_publication_target",
]
