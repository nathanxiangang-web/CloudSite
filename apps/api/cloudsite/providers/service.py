from __future__ import annotations

from ..modules.providers.application.provider_service import provider_info as _provider_info


async def provider_info() -> dict:
    from ..database import StateSession

    async with StateSession() as session:
        return await _provider_info(session)


__all__ = ["provider_info"]
