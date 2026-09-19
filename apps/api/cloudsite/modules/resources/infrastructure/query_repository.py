"""SQLAlchemy read repository for Resources queries."""

from __future__ import annotations

from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..application.queries import ResourceQueryRepository
from ..domain.errors import (
    FolderNotFoundError,
    ResourceInactiveError,
    ResourceNotAvailableError,
    ResourceNotFoundError,
)
from ..domain.views import (
    AdminIndexCountsView,
    AdminIndexFolderView,
    CatalogResourceView,
    DiagnosticResourceView,
    FolderDetailView,
    FolderSummaryView,
    ParentSummaryView,
    ParserResourceView,
    ResourceDetailView,
    ResourceDownloadView,
    ResourcePageView,
    ResourcePreviewView,
    ResourceReferenceView,
    ResourceSummaryView,
)
from .models import Folder, Resource


class SqlAlchemyResourceQueryRepository(ResourceQueryRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _parent_view(folder: Folder | None) -> ParentSummaryView | None:
        if folder is None:
            return None
        return ParentSummaryView(id=folder.id, name=folder.name)

    @classmethod
    def _resource_view(
        cls,
        row: Resource,
        parent: Folder | None = None,
    ) -> ResourceSummaryView:
        return ResourceSummaryView(
            id=row.id,
            name=row.name,
            parent_id=row.parent_id,
            parent=cls._parent_view(parent),
            content_type=row.content_type,
            extension=row.extension,
            mime_type=row.mime_type,
            size=row.size,
            modified_at=row.modified_at,
            status=row.status,
            thumbnail="",
        )

    @staticmethod
    def _admin_index_folder_view(
        row: Folder,
        *,
        direct_resource_count: int | None = None,
    ) -> AdminIndexFolderView:
        return AdminIndexFolderView(
            id=row.id,
            name=row.name,
            parent_id=row.parent_id,
            content_type=row.content_type,
            depth=row.depth,
            child_folder_count=row.child_folder_count,
            resource_count=row.resource_count,
            modified_at=row.modified_at,
            path=row.path,
            root_mapping_id=row.root_mapping_id,
            status=row.status,
            indexed_at=row.indexed_at,
            direct_resource_count=direct_resource_count,
        )

    @staticmethod
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

    async def _breadcrumbs(
        self,
        folder: Folder | None,
    ) -> tuple[ParentSummaryView, ...]:
        items: list[ParentSummaryView] = []
        current = folder
        visited: set[str] = set()
        while current and current.id not in visited:
            visited.add(current.id)
            items.append(ParentSummaryView(id=current.id, name=current.name))
            if not current.parent_id:
                break
            current = await self._session.get(Folder, current.parent_id)
        return tuple(reversed(items))

    async def admin_index_counts(self) -> AdminIndexCountsView:
        folders = int(
            await self._session.scalar(
                select(func.count())
                .select_from(Folder)
                .where(Folder.status == "active")
            )
            or 0
        )
        resources = int(
            await self._session.scalar(
                select(func.count())
                .select_from(Resource)
                .where(Resource.status == "active")
            )
            or 0
        )
        return AdminIndexCountsView(
            folders=folders,
            resources=resources,
        )

    async def admin_index_folders(self) -> list[AdminIndexFolderView]:
        rows = list(
            (
                await self._session.scalars(
                    select(Folder)
                    .where(Folder.status == "active")
                    .order_by(Folder.depth, Folder.path)
                )
            ).all()
        )
        return [
            self._admin_index_folder_view(row)
            for row in rows
        ]

    async def admin_index_folder(
        self,
        *,
        folder_id: str,
    ) -> AdminIndexFolderView | None:
        row = await self._session.get(Folder, folder_id)
        if row is None or row.status != "active":
            return None
        direct_resource_count = int(
            await self._session.scalar(
                select(func.count())
                .select_from(Resource)
                .where(
                    Resource.parent_id == row.id,
                    Resource.status == "active",
                )
            )
            or 0
        )
        return self._admin_index_folder_view(
            row,
            direct_resource_count=direct_resource_count,
        )

    async def catalog_resource(
        self,
        *,
        resource_id: str,
    ) -> CatalogResourceView | None:
        row = await self._session.get(Resource, resource_id)
        if row is None:
            return None
        return CatalogResourceView(
            id=row.id,
            name=row.name,
            extension=row.extension,
            size=row.size,
            status=row.status,
            root_mapping_id=row.root_mapping_id,
            content_type=row.content_type,
        )

    async def diagnostic_resource(
        self,
        *,
        resource_id: str,
    ) -> DiagnosticResourceView | None:
        row = await self._session.get(Resource, resource_id)
        if row is None:
            return None
        return DiagnosticResourceView(
            id=row.id,
            name=row.name,
            path=row.path,
            status=row.status,
            root_mapping_id=row.root_mapping_id,
            content_type=row.content_type,
        )

    async def parser_resource(
        self,
        *,
        resource_id: str,
    ) -> ParserResourceView | None:
        row = await self._session.get(Resource, resource_id)
        if row is None:
            return None
        return ParserResourceView(
            id=row.id,
            name=row.name,
            path=row.path,
            extension=row.extension,
            mime_type=row.mime_type,
            status=row.status,
            content_type=row.content_type,
            size=row.size,
            indexed_at=row.indexed_at,
        )

    async def list_parser_resources(
        self,
        *,
        content_type: str | None,
        limit: int,
    ) -> list[ParserResourceView]:
        query = select(Resource).where(Resource.status == "active")
        if content_type is not None:
            query = query.where(Resource.content_type == content_type)
        rows = list(
            (
                await self._session.scalars(
                    query.order_by(Resource.indexed_at, Resource.id).limit(limit)
                )
            ).all()
        )
        return [
            ParserResourceView(
                id=row.id,
                name=row.name,
                path=row.path,
                extension=row.extension,
                mime_type=row.mime_type,
                status=row.status,
                content_type=row.content_type,
                size=row.size,
                indexed_at=row.indexed_at,
            )
            for row in rows
        ]

    async def resource_references(
        self,
        *,
        resource_ids: list[str],
    ) -> dict[str, ResourceReferenceView]:
        if not resource_ids:
            return {}
        rows = list(
            (
                await self._session.scalars(
                    select(Resource).where(Resource.id.in_(resource_ids))
                )
            ).all()
        )
        return {
            row.id: ResourceReferenceView(
                id=row.id,
                name=row.name,
                parent_id=row.parent_id,
                content_type=row.content_type,
                extension=row.extension,
                mime_type=row.mime_type,
                size=row.size,
                modified_at=row.modified_at,
                status=row.status,
                root_mapping_id=row.root_mapping_id,
            )
            for row in rows
        }

    async def browse_resources(
        self,
        *,
        enabled_root_ids: set[int],
        status: str,
        content_type: str | None,
        page: int,
        page_size: int,
    ) -> ResourcePageView:
        if not enabled_root_ids:
            return ResourcePageView(
                items=(),
                total=0,
                page=page,
                page_size=page_size,
            )
        scope = (
            Resource.status == status,
            Resource.root_mapping_id.in_(enabled_root_ids),
        )
        query = select(Resource).where(*scope)
        count_query = select(func.count()).select_from(Resource).where(*scope)
        if content_type:
            query = query.where(Resource.content_type == content_type)
            count_query = count_query.where(
                Resource.content_type == content_type
            )
        total = int(await self._session.scalar(count_query) or 0)
        rows = list(
            (
                await self._session.scalars(
                    query.order_by(desc(Resource.modified_at), Resource.id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return ResourcePageView(
            items=tuple(self._resource_view(row) for row in rows),
            total=total,
            page=page,
            page_size=page_size,
        )

    async def browse_resource_counts(
        self,
        *,
        enabled_root_ids: set[int],
        status: str,
        content_types: tuple[str, ...],
    ) -> dict[str, int]:
        if not enabled_root_ids or not content_types:
            return {}
        rows = (
            await self._session.execute(
                select(Resource.content_type, func.count())
                .select_from(Resource)
                .where(
                    Resource.status == status,
                    Resource.root_mapping_id.in_(enabled_root_ids),
                    Resource.content_type.in_(content_types),
                )
                .group_by(Resource.content_type)
            )
        ).all()
        return {
            str(content_type): int(count or 0)
            for content_type, count in rows
        }

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
        parents: dict[str, Folder] = {}
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
            self._resource_view(row, parents.get(row.parent_id or ""))
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
        return [self._folder_view(row) for row in rows]

    async def resource_detail(
        self,
        *,
        resource_id: str,
        enabled_root_ids: set[int],
    ) -> ResourceDetailView:
        row = await self._session.get(Resource, resource_id)
        if row is None or row.status != "active":
            raise ResourceNotFoundError(resource_id)
        if (
            row.root_mapping_id is None
            or row.root_mapping_id not in enabled_root_ids
        ):
            raise ResourceNotAvailableError(resource_id)

        parent = (
            await self._session.get(Folder, row.parent_id)
            if row.parent_id
            else None
        )
        breadcrumbs = await self._breadcrumbs(parent)

        sibling_scope = (
            Resource.status == "active",
            Resource.parent_id == row.parent_id,
            Resource.root_mapping_id == row.root_mapping_id,
            Resource.root_mapping_id.in_(enabled_root_ids),
        )
        related = list(
            (
                await self._session.scalars(
                    select(Resource)
                    .where(*sibling_scope, Resource.id != row.id)
                    .order_by(desc(Resource.modified_at))
                    .limit(8)
                )
            ).all()
        )
        previous = (
            await self._session.scalars(
                select(Resource)
                .where(
                    *sibling_scope,
                    Resource.content_type == row.content_type,
                    or_(
                        Resource.name < row.name,
                        and_(Resource.name == row.name, Resource.id < row.id),
                    ),
                )
                .order_by(desc(Resource.name), desc(Resource.id))
                .limit(1)
            )
        ).first()
        next_item = (
            await self._session.scalars(
                select(Resource)
                .where(
                    *sibling_scope,
                    Resource.content_type == row.content_type,
                    or_(
                        Resource.name > row.name,
                        and_(Resource.name == row.name, Resource.id > row.id),
                    ),
                )
                .order_by(Resource.name, Resource.id)
                .limit(1)
            )
        ).first()

        return ResourceDetailView(
            resource=self._resource_view(row, parent),
            breadcrumbs=breadcrumbs,
            related=tuple(self._resource_view(item, parent) for item in related),
            previous=self._resource_view(previous, parent) if previous else None,
            next=self._resource_view(next_item, parent) if next_item else None,
        )

    async def preview_resource(
        self,
        *,
        resource_id: str,
        enabled_root_ids: set[int],
    ) -> ResourcePreviewView:
        row = await self._session.get(Resource, resource_id)
        if row is None or row.status != "active":
            raise ResourceNotFoundError(resource_id)
        if (
            row.root_mapping_id is None
            or row.root_mapping_id not in enabled_root_ids
        ):
            raise ResourceNotAvailableError(resource_id)

        return ResourcePreviewView(
            id=row.id,
            name=row.name,
            path=row.path,
            root_mapping_id=row.root_mapping_id,
            extension=row.extension,
            mime_type=row.mime_type,
            size=row.size,
            status=row.status,
        )

    async def download_resource(
        self,
        *,
        resource_id: str,
        enabled_root_ids: set[int],
    ) -> ResourceDownloadView:
        row = await self._session.get(Resource, resource_id)
        if row is None or row.status == "missing":
            raise ResourceNotFoundError(resource_id)
        if row.status != "active":
            raise ResourceInactiveError(resource_id)
        if (
            row.root_mapping_id is None
            or row.root_mapping_id not in enabled_root_ids
        ):
            raise ResourceNotAvailableError(resource_id)

        return ResourceDownloadView(
            id=row.id,
            path=row.path,
            root_mapping_id=row.root_mapping_id,
            status=row.status,
        )

    async def folder_detail(
        self,
        *,
        folder_id: str,
        enabled_root_ids: set[int],
        page: int,
        page_size: int,
        sort: str,
        order: str,
    ) -> FolderDetailView:
        row = await self._session.get(Folder, folder_id)
        if (
            row is None
            or row.status != "active"
            or row.root_mapping_id not in enabled_root_ids
        ):
            raise FolderNotFoundError(folder_id)

        breadcrumbs = await self._breadcrumbs(row)
        child_folders = list(
            (
                await self._session.scalars(
                    select(Folder)
                    .where(
                        Folder.parent_id == folder_id,
                        Folder.status == "active",
                        Folder.root_mapping_id.in_(enabled_root_ids),
                    )
                    .order_by(Folder.name)
                )
            ).all()
        )

        resource_scope = (
            Resource.parent_id == folder_id,
            Resource.status == "active",
            Resource.root_mapping_id.in_(enabled_root_ids),
        )
        total = int(
            await self._session.scalar(
                select(func.count()).select_from(Resource).where(*resource_scope)
            )
            or 0
        )
        sort_columns = {
            "name": Resource.name,
            "modified_at": Resource.modified_at,
            "size": Resource.size,
        }
        sort_column = sort_columns[sort]
        order_by = sort_column.asc() if order == "asc" else sort_column.desc()
        child_resources = list(
            (
                await self._session.scalars(
                    select(Resource)
                    .where(*resource_scope)
                    .order_by(order_by, Resource.id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )

        return FolderDetailView(
            folder=self._folder_view(row),
            breadcrumbs=breadcrumbs,
            child_folders=tuple(self._folder_view(item) for item in child_folders),
            resources=ResourcePageView(
                items=tuple(
                    self._resource_view(item, row) for item in child_resources
                ),
                total=total,
                page=page,
                page_size=page_size,
            ),
        )


__all__ = ["SqlAlchemyResourceQueryRepository"]
