from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from ... import database as _database


# Compatibility injection hooks.
#
# Keep these names available because existing tests/composition code monkeypatch
# platform.db.session.StateSession / IndexSession.  Leaving them as None by
# default avoids caching the legacy factories at import time; runtime lookup
# still follows the current cloudsite.database factory unless explicitly
# overridden.
StateSession: Callable[[], AsyncSession] | None = None
IndexSession: Callable[[], AsyncSession] | None = None


def _state_factory():
    return StateSession or _database.StateSession


def _index_factory():
    return IndexSession or _database.IndexSession


@asynccontextmanager
async def state_session() -> AsyncIterator[AsyncSession]:
    async with _state_factory()() as session:
        yield session


@asynccontextmanager
async def index_session() -> AsyncIterator[AsyncSession]:
    async with _index_factory()() as session:
        yield session


async def get_state_session() -> AsyncSession:
    return _state_factory()()


async def get_index_session() -> AsyncSession:
    return _index_factory()()


__all__ = [
    "StateSession",
    "IndexSession",
    "get_state_session",
    "get_index_session",
    "state_session",
    "index_session",
]
