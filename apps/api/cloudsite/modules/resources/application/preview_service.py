"""Resources preview application service."""

from __future__ import annotations

from urllib.parse import urlencode

from ....config import settings
from cloudsite.modules.providers.contracts.public import (
    ProviderAccessError,
    ProviderRuntimePort,
    ProviderUnavailableError,
)
from ....preview import create_preview_ticket, preview_capability
from ..domain.errors import ResourceNotAvailableError, ResourceNotFoundError
from ..domain.preview import ResourcePreviewError
from ..domain.views import ResourcePreviewView
from ..infrastructure.preview_cache import (
    cache_preview_from_url,
    fresh_preview_cache_path,
    preview_cache_filename,
)
from .queries import ResourceQueries


class ResourcePreviewService:
    def __init__(
        self,
        queries: ResourceQueries,
        provider: ProviderRuntimePort,
    ) -> None:
        self._queries = queries
        self._provider = provider

    async def _resource(
        self,
        *,
        resource_id: str,
        enabled_root_ids: set[int],
    ) -> ResourcePreviewView:
        try:
            return await self._queries.preview_resource(
                resource_id=resource_id,
                enabled_root_ids=enabled_root_ids,
            )
        except (ResourceNotFoundError, ResourceNotAvailableError) as exc:
            raise ResourcePreviewError(
                "PV-001",
                "资源不存在或已不可用",
                404,
            ) from exc

    async def _cached_path(
        self,
        resource: ResourcePreviewView,
    ):
        cached = fresh_preview_cache_path(resource)
        if cached is not None:
            return cached

        if resource.root_mapping_id is None:
            raise ResourcePreviewError(
                "PV-005",
                "上游存储暂时不可用",
                503,
            )

        try:
            entry = await self._provider.download_entry(
                root_mapping_id=resource.root_mapping_id,
                path=resource.path,
            )
            source_url = entry.url
        except ProviderUnavailableError as exc:
            raise ResourcePreviewError(
                "PV-005",
                "上游存储暂时不可用",
                503,
            ) from exc
        except ProviderAccessError as exc:
            raise ResourcePreviewError(
                "PV-003",
                "无法获取 Office 预览入口",
                503,
            ) from exc

        return await cache_preview_from_url(resource, source_url)

    async def capability(
        self,
        *,
        resource_id: str,
        enabled_root_ids: set[int],
    ) -> dict:
        resource = await self._resource(
            resource_id=resource_id,
            enabled_root_ids=enabled_root_ids,
        )
        return preview_capability(resource)

    async def text_preview(
        self,
        *,
        resource_id: str,
        enabled_root_ids: set[int],
    ) -> dict:
        resource = await self._resource(
            resource_id=resource_id,
            enabled_root_ids=enabled_root_ids,
        )
        capability = preview_capability(resource)
        if (
            not capability["can_preview"]
            or capability["preview_type"] not in {"text", "markdown"}
        ):
            raise ResourcePreviewError(
                "PV-002",
                capability["reason"] or "资源不支持文本预览",
                400,
            )
        if resource.size > settings.text_preview_max_bytes:
            raise ResourcePreviewError(
                "PV-007",
                "文本文件过大，不提供在线预览",
                413,
            )

        cached_path = await self._cached_path(resource)
        try:
            raw = cached_path.read_bytes()
        except Exception as exc:
            raise ResourcePreviewError(
                "PV-999",
                "读取缓存文件失败",
            ) from exc

        max_bytes = settings.text_preview_max_bytes
        truncated = len(raw) > max_bytes
        if truncated:
            raw = raw[:max_bytes]

        return {
            "content": raw.decode("utf-8", errors="replace"),
            "truncated": truncated,
            "size": resource.size,
            "encoding": "utf-8",
            "preview_type": capability["preview_type"],
        }

    async def cached_preview_url(
        self,
        *,
        resource_id: str,
        enabled_root_ids: set[int],
        expected_type: str,
    ) -> str:
        resource = await self._resource(
            resource_id=resource_id,
            enabled_root_ids=enabled_root_ids,
        )
        capability = preview_capability(resource)
        if capability["preview_type"] != expected_type:
            label = "PDF" if expected_type == "pdf" else "Office"
            raise ResourcePreviewError(
                "PV-002",
                f"该资源不支持 {label} 在线预览",
                400,
            )

        await self._cached_path(resource)
        ticket = create_preview_ticket(resource.id)
        return (
            f"/office-files/{preview_cache_filename(resource)}?"
            f"{urlencode({'ticket': ticket})}"
        )


__all__ = ["ResourcePreviewService"]
