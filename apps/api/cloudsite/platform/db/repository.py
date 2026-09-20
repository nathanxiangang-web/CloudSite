from __future__ import annotations

from typing import Any, Generic, Protocol, TypeVar, runtime_checkable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar('T')
ID = TypeVar('ID')


@runtime_checkable
class Repository(Protocol, Generic[T, ID]):
    async def get(self, session: AsyncSession, id: ID) -> T | None: ...
    async def list(self, session: AsyncSession, *, offset: int = 0, limit: int = 50) -> list[T]: ...
    async def add(self, session: AsyncSession, entity: T) -> T: ...
    async def remove(self, session: AsyncSession, entity: T) -> None: ...


class GenericRepository(Generic[T, ID]):
    def __init__(self, model: type[T]):
        self._model = model

    async def get(self, session: AsyncSession, id: ID) -> T | None:
        return await session.get(self._model, id)

    async def get_by(self, session: AsyncSession, **filters: Any) -> T | None:
        stmt = select(self._model).filter_by(**filters)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(self, session: AsyncSession, *, offset: int = 0, limit: int = 50, **filters: Any) -> list[T]:
        stmt = select(self._model)
        if filters:
            stmt = stmt.filter_by(**filters)
        stmt = stmt.offset(offset).limit(limit)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def add(self, session: AsyncSession, entity: T) -> T:
        session.add(entity)
        await session.flush()
        return entity

    async def remove(self, session: AsyncSession, entity: T) -> None:
        await session.delete(entity)

    async def count(self, session: AsyncSession, **filters: Any) -> int:
        from sqlalchemy import func
        stmt = select(func.count()).select_from(self._model)
        if filters:
            stmt = stmt.filter_by(**filters)
        result = await session.execute(stmt)
        return result.scalar_one()


__all__ = ['Repository', 'GenericRepository']
