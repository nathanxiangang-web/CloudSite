"""Read-only bridge over legacy sync tables for Automation seeding."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.parser_seed import ParserSeedChangeView, ParserSeedRunView


async def parser_seed_run(
    session: AsyncSession,
    *,
    sync_run_id: int,
) -> ParserSeedRunView | None:
    row = (
        await session.execute(
            text("SELECT id, status FROM sync_runs WHERE id = :sync_run_id"),
            {"sync_run_id": sync_run_id},
        )
    ).first()
    if row is None:
        return None
    return ParserSeedRunView(id=int(row[0]), status=str(row[1]))


async def parser_seed_changes(
    session: AsyncSession,
    *,
    sync_run_id: int,
    after_change_id: int,
    limit: int,
) -> tuple[ParserSeedChangeView, ...]:
    rows = (
        await session.execute(
            text(
                "SELECT id, object_type, object_id, change_type "
                "FROM sync_changes "
                "WHERE sync_run_id = :sync_run_id AND id > :after_change_id "
                "ORDER BY id ASC LIMIT :limit"
            ),
            {
                "sync_run_id": sync_run_id,
                "after_change_id": after_change_id,
                "limit": limit,
            },
        )
    ).all()
    return tuple(
        ParserSeedChangeView(
            id=int(row[0]),
            object_type=str(row[1]),
            object_id=str(row[2]),
            change_type=str(row[3]),
        )
        for row in rows
    )


__all__ = ["parser_seed_run", "parser_seed_changes"]
