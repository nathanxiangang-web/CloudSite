"""Read-only admin overview queries owned by Delivery."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure.models import DownloadEvent


async def failed_download_count(state: AsyncSession) -> int:
    return int(
        await state.scalar(
            select(func.count())
            .select_from(DownloadEvent)
            .where(DownloadEvent.result == "failed")
        )
        or 0
    )


__all__ = ["failed_download_count"]
