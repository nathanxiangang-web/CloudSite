"""Providers-owned runtime gateway.

Connection ORM, encrypted credentials, decryption, and AList client construction
stay inside the Providers boundary. Callers receive only provider operations or
persistence-neutral results.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ....alist import AListClient, AListError
from ....crypto import decrypt_secret
from ..domain.runtime import (
    ProviderAccessError,
    ProviderEntry,
    ProviderRuntimePort,
    ProviderUnavailableError,
)
from .models import AListConnection, ContentRootMapping
from .registry import registry


def _provider_error(exc: Exception) -> ProviderAccessError:
    if isinstance(exc, AListError):
        if exc.code == "AL-002":
            return ProviderAccessError(
                "unreachable",
                "provider temporarily unreachable",
                status_code=503,
            )
        if exc.code in {"AL-003", "AL-004"}:
            return ProviderAccessError(
                "authentication",
                "provider authentication failed",
                status_code=503,
            )
        if exc.code == "AL-005":
            return ProviderAccessError(
                "metadata",
                "provider metadata lookup failed",
                status_code=exc.status_code if exc.status_code == 429 else 502,
            )
        if exc.code == "AL-001":
            return ProviderAccessError(
                "configuration",
                "provider configuration invalid",
                status_code=502,
            )
    if isinstance(exc, ValueError):
        return ProviderAccessError(
            "credentials",
            "provider credentials are invalid",
            status_code=503,
        )
    return ProviderAccessError("unknown", "provider operation failed", status_code=502)


class SqlAlchemyProviderRuntimeGateway(ProviderRuntimePort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _connection_for_root(self, root_mapping_id: int) -> AListConnection:
        mapping = await self._session.get(ContentRootMapping, root_mapping_id)
        if mapping is None or not mapping.enabled:
            raise ProviderUnavailableError("content root is unavailable")

        connection = await self._session.get(AListConnection, mapping.connection_id)
        if connection is None or not connection.enabled:
            raise ProviderUnavailableError("provider connection is unavailable")

        return connection

    async def _entry(
        self,
        *,
        root_mapping_id: int,
        path: str,
        preview: bool,
    ) -> ProviderEntry:
        connection = await self._connection_for_root(root_mapping_id)
        try:
            password = decrypt_secret(connection.password_ciphertext)
            async with AListClient(
                connection.base_url,
                connection.username,
                password,
            ) as client:
                provider = registry.wrap(client, connection.provider_type)
                entry = (
                    await provider.get_preview_entry(path)
                    if preview
                    else await provider.get_download_entry(path)
                )
        except ProviderUnavailableError:
            raise
        except Exception as exc:
            raise _provider_error(exc) from exc

        return ProviderEntry(
            url=entry.url,
            host=entry.host,
            base_path=entry.base_path,
            has_sign=entry.has_sign,
        )

    async def download_entry(
        self,
        *,
        root_mapping_id: int,
        path: str,
    ) -> ProviderEntry:
        return await self._entry(
            root_mapping_id=root_mapping_id,
            path=path,
            preview=False,
        )

    async def preview_entry(
        self,
        *,
        root_mapping_id: int,
        path: str,
    ) -> ProviderEntry:
        return await self._entry(
            root_mapping_id=root_mapping_id,
            path=path,
            preview=True,
        )


__all__ = ["SqlAlchemyProviderRuntimeGateway"]
