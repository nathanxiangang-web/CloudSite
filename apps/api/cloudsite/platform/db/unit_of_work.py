from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from ...database import StateSession, IndexSession


class UnitOfWork:
    """Coordinates state + index sessions with explicit commit/rollback.

    SQLite uses two separate databases (state.db, index.db) so cross-db
    transactions are NOT atomic. Callers must design for eventual
    consistency or use the task/outbox pattern for compensation.
    """

    def __init__(self) -> None:
        self.state: AsyncSession | None = None
        self.index: AsyncSession | None = None

    async def __aenter__(self) -> UnitOfWork:
        self.state = StateSession()
        self.index = IndexSession()
        await self.state.__aenter__()
        await self.index.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        try:
            if exc_type is None:
                await self.state.commit()
                await self.index.commit()
            else:
                await self.state.rollback()
                await self.index.rollback()
        finally:
            await self.state.__aexit__(exc_type, exc_val, exc_tb)
            await self.index.__aexit__(exc_type, exc_val, exc_tb)
            self.state = None
            self.index = None

    async def commit(self) -> None:
        await self.state.commit()
        await self.index.commit()

    async def rollback(self) -> None:
        await self.state.rollback()
        await self.index.rollback()


__all__ = ['UnitOfWork']
