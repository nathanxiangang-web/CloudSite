from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from ...database import StateSession, IndexSession


@asynccontextmanager
async def state_session() -> AsyncIterator[AsyncSession]:
    async with StateSession() as session:
        yield session


@asynccontextmanager
async def index_session() -> AsyncIterator[AsyncSession]:
    async with IndexSession() as session:
        yield session


async def get_state_session() -> AsyncSession:
    return StateSession()


async def get_index_session() -> AsyncSession:
    return IndexSession()


__all__ = ['get_state_session', 'get_index_session', 'state_session', 'index_session']
