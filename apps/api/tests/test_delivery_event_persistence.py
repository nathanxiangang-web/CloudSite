"""Delivery event persistence behavior tests."""

import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.modules.delivery.application.download_event import _download_event
from cloudsite.modules.delivery.infrastructure.models import DownloadEvent
from cloudsite.platform.db import StateBase


async def test_download_event_preserves_commit_and_payload_behavior():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)

    started = time.perf_counter() - 0.01
    async with factory() as session:
        await _download_event(
            session,
            "r_event",
            "failed",
            "DL-002",
            started,
            source="public",
        )

    async with factory() as session:
        row = await session.scalar(
            select(DownloadEvent).where(DownloadEvent.resource_id == "r_event")
        )
        assert row is not None
        assert row.result == "failed"
        assert row.error_code == "DL-002"
        assert row.source == "public"
        assert row.duration_ms >= 0

    await engine.dispose()
