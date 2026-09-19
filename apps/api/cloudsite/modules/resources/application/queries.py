"""Application query boundary for Resources read views."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.views import (
    AdminIndexCountsView,
    AdminIndexFolderView,
    CatalogResourceView,
    DiagnosticResourceView,
    FolderDetailView,
    FolderSummaryView,
    HomeInventoryView,
    ParserResourceView,
    ResourceDetailView,
    ResourceDownloadView,
    ResourcePageView,
    ResourcePreviewView,
    ResourceReferenceView,
    SearchDocumentView,
    SearchObjectBatchView,
)


@runtime_checkable
class ResourceQueryRepository(Protocol):
    async def search_documents(self) -> list[SearchDocumentView]: ...

    async def search_objects(
        self,
        *,
        resource_ids: list[str],
        folder_ids: list[str],
        enabled_root_ids: set[int],
    ) -> SearchObjectBatchView: ...

    async def admin_index_counts(self) -> AdminIndexCountsView: ...

    async def admin_content_type_counts(
        self,
        *,
        content_types: tuple[str, ...],
    ) -> dict[str, int]: ...

    async def home_inventory(
        self,
        *,
        enabled_root_ids: set[int],
        content_types: tuple[str, ...],
        recent_limit: int,
        popular_limit: int,
        popular_strategy: str,
        featured_resource_ids: list[str],
        manual_root_order: tuple[int, ...],
    ) -> HomeInventoryView: ...

    async def root_inventory_counts(
        self,
        *,
        enabled_root_ids: set[int],
    ) -> tuple[dict[int, int], dict[int, int]]: ...

    async def admin_index_folders(self) -> list[AdminIndexFolderView]: ...

    async def admin_index_folder(
        self,
        *,
        folder_id: str,
    ) -> AdminIndexFolderView | None: ...

    async def catalog_resource(
        self,
        *,
        resource_id: str,
    ) -> CatalogResourceView | None: ...

    async def diagnostic_resource(
        self,
        *,
        resource_id: str,
    ) -> DiagnosticResourceView | None: ...

    async def parser_resource(
        self,
        *,
        resource_id: str,
    ) -> ParserResourceView | None: ...

    async def list_parser_resources(
        self,
        *,
        content_type: str | None,
        limit: int,
    ) -> list[ParserResourceView]: ...

    async def resource_references(
        self,
        *,
        resource_ids: list[str],
    ) -> dict[str, ResourceReferenceView]: ...

    async def browse_resources(
        self,
        *,
        enabled_root_ids: set[int],
        status: str,
        content_type: str | None,
        page: int,
        page_size: int,
    ) -> ResourcePageView: ...

    async def browse_resource_counts(
        self,
        *,
        enabled_root_ids: set[int],
        status: str,
        content_types: tuple[str, ...],
    ) -> dict[str, int]: ...

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
    ) -> ResourcePageView: ...

    async def list_folders(
        self,
        *,
        enabled_root_ids: set[int],
        content_type: str | None,
        parent_id: str | None,
        parent_filter_supplied: bool,
    ) -> list[FolderSummaryView]: ...

    async def resource_detail(
        self,
        *,
        resource_id: str,
        enabled_root_ids: set[int],
    ) -> ResourceDetailView: ...

    async def folder_detail(
        self,
        *,
        folder_id: str,
        enabled_root_ids: set[int],
        page: int,
        page_size: int,
        sort: str,
        order: str,
    ) -> FolderDetailView: ...

    async def preview_resource(
        self,
        *,
        resource_id: str,
        enabled_root_ids: set[int],
    ) -> ResourcePreviewView: ...

    async def download_resource(
        self,
        *,
        resource_id: str,
        enabled_root_ids: set[int],
    ) -> ResourceDownloadView: ...


class ResourceQueries:
    def __init__(self, repository: ResourceQueryRepository) -> None:
        self._repository = repository

    async def search_documents(self) -> list[SearchDocumentView]:
        return await self._repository.search_documents()

    async def search_objects(
        self,
        *,
        resource_ids: list[str],
        folder_ids: list[str],
        enabled_root_ids: set[int],
    ) -> SearchObjectBatchView:
        return await self._repository.search_objects(
            resource_ids=list(dict.fromkeys(resource_ids)),
            folder_ids=list(dict.fromkeys(folder_ids)),
            enabled_root_ids=set(enabled_root_ids),
        )

    async def admin_index_counts(self) -> AdminIndexCountsView:
        return await self._repository.admin_index_counts()

    async def admin_content_type_counts(
        self,
        *,
        content_types: tuple[str, ...],
    ) -> dict[str, int]:
        return await self._repository.admin_content_type_counts(
            content_types=content_types,
        )

    async def home_inventory(
        self,
        *,
        enabled_root_ids: set[int],
        content_types: tuple[str, ...],
        recent_limit: int,
        popular_limit: int,
        popular_strategy: str,
        featured_resource_ids: list[str] | None = None,
        manual_root_order: tuple[int, ...] = (),
    ) -> HomeInventoryView:
        return await self._repository.home_inventory(
            enabled_root_ids=set(enabled_root_ids),
            content_types=tuple(content_types),
            recent_limit=max(int(recent_limit), 0),
            popular_limit=max(int(popular_limit), 0),
            popular_strategy=popular_strategy,
            featured_resource_ids=list(featured_resource_ids or []),
            manual_root_order=tuple(manual_root_order),
        )

    async def root_inventory_counts(
        self,
        *,
        enabled_root_ids: set[int],
    ) -> tuple[dict[int, int], dict[int, int]]:
        return await self._repository.root_inventory_counts(
            enabled_root_ids=set(enabled_root_ids),
        )

    async def admin_index_folders(self) -> list[AdminIndexFolderView]:
        return await self._repository.admin_index_folders()

    async def admin_index_folder(
        self,
        *,
        folder_id: str,
    ) -> AdminIndexFolderView | None:
        return await self._repository.admin_index_folder(
            folder_id=folder_id,
        )

    async def catalog_resource(
        self,
        *,
        resource_id: str,
    ) -> CatalogResourceView | None:
        return await self._repository.catalog_resource(
            resource_id=resource_id,
        )

    async def diagnostic_resource(
        self,
        *,
        resource_id: str,
    ) -> DiagnosticResourceView | None:
        return await self._repository.diagnostic_resource(
            resource_id=resource_id,
        )

    async def parser_resource(
        self,
        *,
        resource_id: str,
    ) -> ParserResourceView | None:
        return await self._repository.parser_resource(
            resource_id=resource_id,
        )

    async def list_parser_resources(
        self,
        *,
        content_type: str | None = None,
        limit: int = 200,
    ) -> list[ParserResourceView]:
        return await self._repository.list_parser_resources(
            content_type=content_type,
            limit=max(int(limit), 0),
        )

    async def resource_references(
        self,
        *,
        resource_ids: list[str],
    ) -> dict[str, ResourceReferenceView]:
        return await self._repository.resource_references(
            resource_ids=list(dict.fromkeys(resource_ids)),
        )

    async def browse_resources(
        self,
        *,
        enabled_root_ids: set[int],
        status: str,
        content_type: str | None,
        page: int,
        page_size: int,
    ) -> ResourcePageView:
        return await self._repository.browse_resources(
            enabled_root_ids=enabled_root_ids,
            status=status,
            content_type=content_type,
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
        return await self._repository.browse_resource_counts(
            enabled_root_ids=enabled_root_ids,
            status=status,
            content_types=content_types,
        )

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
        return await self._repository.list_resources(
            enabled_root_ids=enabled_root_ids,
            content_type=content_type,
            parent_id=parent_id,
            page=page,
            page_size=page_size,
            sort=sort,
            order=order,
        )

    async def list_folders(
        self,
        *,
        enabled_root_ids: set[int],
        content_type: str | None,
        parent_id: str | None,
        parent_filter_supplied: bool,
    ) -> list[FolderSummaryView]:
        return await self._repository.list_folders(
            enabled_root_ids=enabled_root_ids,
            content_type=content_type,
            parent_id=parent_id,
            parent_filter_supplied=parent_filter_supplied,
        )

    async def resource_detail(
        self,
        *,
        resource_id: str,
        enabled_root_ids: set[int],
    ) -> ResourceDetailView:
        return await self._repository.resource_detail(
            resource_id=resource_id,
            enabled_root_ids=enabled_root_ids,
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
        return await self._repository.folder_detail(
            folder_id=folder_id,
            enabled_root_ids=enabled_root_ids,
            page=page,
            page_size=page_size,
            sort=sort,
            order=order,
        )

    async def preview_resource(
        self,
        *,
        resource_id: str,
        enabled_root_ids: set[int],
    ) -> ResourcePreviewView:
        return await self._repository.preview_resource(
            resource_id=resource_id,
            enabled_root_ids=enabled_root_ids,
        )

    async def download_resource(
        self,
        *,
        resource_id: str,
        enabled_root_ids: set[int],
    ) -> ResourceDownloadView:
        return await self._repository.download_resource(
            resource_id=resource_id,
            enabled_root_ids=enabled_root_ids,
        )


__all__ = ["ResourceQueries", "ResourceQueryRepository"]
