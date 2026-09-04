"""CloudSite schema migration framework.

显式 schema_version + 单向 migration chain + 幂等。
- state.db schema_version 存于 system_settings(key='schema_version')
- index.db schema_version 存于 _schema_meta(key='schema_version')

1.0 baseline: 现有 init_databases 的幂等 ALTER 逻辑归为 schema_version 1。
未来新增字段追加 Migration(from=N, to=N+1) 并注册到 chain，保持只向前迁移。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncConnection

CURRENT_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class Migration:
    """一条单向 schema migration，upgrade 必须幂等。"""

    id: str
    from_version: int
    to_version: int
    upgrade: Callable[[AsyncConnection], Awaitable[None]]


async def get_state_schema_version(conn: AsyncConnection) -> int:
    row = await conn.exec_driver_sql(
        "SELECT value FROM system_settings WHERE key='schema_version'"
    )
    r = row.fetchone()
    return int(r[0]) if r else 0


async def set_state_schema_version(conn: AsyncConnection, version: int) -> None:
    await conn.exec_driver_sql(
        "INSERT OR REPLACE INTO system_settings(key, value, value_type, updated_at) "
        "VALUES('schema_version', ?, 'integer', CURRENT_TIMESTAMP)",
        (str(version),),
    )


async def get_index_schema_version(conn: AsyncConnection) -> int:
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS _schema_meta("
        "key VARCHAR(40) PRIMARY KEY, value VARCHAR(40) NOT NULL)"
    )
    row = await conn.exec_driver_sql(
        "SELECT value FROM _schema_meta WHERE key='schema_version'"
    )
    r = row.fetchone()
    return int(r[0]) if r else 0


async def set_index_schema_version(conn: AsyncConnection, version: int) -> None:
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS _schema_meta("
        "key VARCHAR(40) PRIMARY KEY, value VARCHAR(40) NOT NULL)"
    )
    await conn.exec_driver_sql(
        "INSERT OR REPLACE INTO _schema_meta(key, value) "
        "VALUES('schema_version', ?)",
        (str(version),),
    )


async def run_migrations(
    conn: AsyncConnection,
    chain: list[Migration],
    get_version: Callable[[AsyncConnection], Awaitable[int]],
    set_version: Callable[[AsyncConnection, int], Awaitable[None]],
) -> tuple[int, list[str]]:
    """跑单向 migration chain，返回 (最终版本, 已应用 migration id 列表)。

    只向前：对 from_version <= cur < to_version 的 migration 依次执行。
    每条 upgrade 必须幂等；失败抛异常则调用方不应启动 Scheduler/Sync。
    """
    cur = await get_version(conn)
    applied: list[str] = []
    for m in chain:
        if m.from_version <= cur < m.to_version:
            await m.upgrade(conn)
            cur = m.to_version
            await set_version(conn, cur)
            applied.append(m.id)
    return cur, applied
