"""Application query boundary for Resources read views."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.views import (
    FolderDetailView,
    FolderSummaryView,
    ResourceDetailView,
    ResourceDownloadView,
    ResourcePageView,
    ResourcePreviewView,
)


@runtime_checkable
class ResourceQueryRepository(Protocol):
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
