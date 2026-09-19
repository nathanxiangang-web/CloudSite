"""Resources preview service composition."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from cloudsite.modules.providers.contracts.public import provider_runtime
from ..application.preview_service import ResourcePreviewService
from .queries import resource_queries


def resource_preview_service(
    index_session: AsyncSession,
    state_session: AsyncSession,
) -> ResourcePreviewService:
    return ResourcePreviewService(
        resource_queries(index_session),
        provider_runtime(state_session),
    )


__all__ = ["resource_preview_service"]
