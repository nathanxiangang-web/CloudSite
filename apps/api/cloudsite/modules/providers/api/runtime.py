"""Public composition helpers for Providers runtime operations."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.runtime import ProviderRuntimePort
from ..infrastructure.runtime_gateway import SqlAlchemyProviderRuntimeGateway


def provider_runtime(session: AsyncSession) -> ProviderRuntimePort:
    return SqlAlchemyProviderRuntimeGateway(session)


__all__ = ["provider_runtime"]
