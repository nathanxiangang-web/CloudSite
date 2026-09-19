"""SQLAlchemy read repository for Resources list queries."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..application.queries import ResourceQueryRepository
from ..domain.views import (
    FolderSummaryView,
    ParentSummaryView,
    ResourcePageView,
    ResourceSummaryView,
)
from .models import Folder, Resource


class SqlAlchemyResourceQueryRepository(ResourceQueryRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_resources(
        self,
        *,
        enabled_root_ids: set[int],
        content_type: str | None,
        parent_id: str | None,
        page: int,
        page_size: int,
        sort: str,
        order: str,
    ) -> ResourcePageView:
        if not enabled_root_ids:
            return ResourcePageView(items=(), total=0, page=page, page_size=page_size)

        scope = (
            Resource.status == "active",
            Resource.root_mapping_id.in_(enabled_root_ids),
        )
        query = select(Resource).where(*scope)
        count_query = select(func.count()).select_from(Resource).where(*scope)

        if content_type:
            query = query.where(Resource.content_type == content_type)
            count_query = count_query.where(Resource.content_type == content_type)
        if parent_id:
            query = query.where(Resource.parent_id == parent_id)
            count_query = count_query.where(Resource.parent_id == parent_id)

        sort_columns = {
            "name": Resource.name,
            "modified_at": Resource.modified_at,
            "modified": Resource.modified_at,
            "size": Resource.size,
        }
        sort_column = sort_columns[sort]
        order_by = sort_column.asc() if order == "asc" else sort_column.desc()

        total = int(await self._session.scalar(count_query) or 0)
        rows = list(
            (
                await self._session.scalars(
                    query.order_by(order_by, Resource.id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )

        parent_ids = {row.parent_id for row in rows if row.parent_id}
        parents = {}
        if parent_ids:
            parent_rows = (
                await self._session.scalars(
                    select(Folder).where(
                        Folder.id.in_(parent_ids),
                        Folder.status == "active",
                    )
                )
            ).all()
            parents = {row.id: row for row in parent_rows}

        items = tuple(
            ResourceSummaryView(
                id=row.id,
                name=row.name,
                parent_id=row.parent_id,
                parent=(
                    ParentSummaryView(
                        id=parents[row.parent_id].id,
                        name=parents[row.parent_id].name,
                    )
                    if row.parent_id in parents
                    else None
                ),
                content_type=row.content_type,
                extension=row.extension,
                mime_type=row.mime_type,
                size=row.size,
                modified_at=row.modified_at,
                thumbnail="",
            )
            for row in rows
        )
        return ResourcePageView(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
        )

    async def list_folders(
        self,
        *,
        enabled_root_ids: set[int],
        content_type: str | None,
        parent_id: str | None,
        parent_filter_supplied: bool,
    ) -> list[FolderSummaryView]:
        if not enabled_root_ids:
            return []

        query = select(Folder).where(
            Folder.status == "active",
            Folder.root_mapping_id.in_(enabled_root_ids),
        )
        if content_type:
            query = query.where(Folder.content_type == content_type)
        if parent_filter_supplied:
            query = query.where(Folder.parent_id == (parent_id or None))

        rows = list(
            (
                await self._session.scalars(
                    query.order_by(Folder.depth, Folder.name)
                )
            ).all()
        )
        return [
            FolderSummaryView(
                id=row.id,
                name=row.name,
                parent_id=row.parent_id,
                content_type=row.content_type,
                depth=row.depth,
                child_folder_count=row.child_folder_count,
                resource_count=row.resource_count,
                modified_at=row.modified_at,
            )
            for row in rows
        ]


__all__ = ["SqlAlchemyResourceQueryRepository"]
