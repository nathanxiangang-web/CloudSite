"""Application query boundary for resource/folder list views."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.views import FolderSummaryView, ResourcePageView


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


__all__ = ["ResourceQueries", "ResourceQueryRepository"]
