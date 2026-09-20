from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable

MigrationFn = Callable[..., Awaitable[None]]


@dataclass
class MigrationEntry:
    version: int
    description: str
    fn: MigrationFn
    database: str = 'state'


class MigrationRegistry:
    def __init__(self) -> None:
        self._entries: list[MigrationEntry] = []
        self._versions: set[int] = set()

    def register(self, version: int, description: str, fn: MigrationFn, *, database: str = 'state') -> None:
        if version in self._versions:
            raise ValueError(f'Migration version {version} already registered')
        self._versions.add(version)
        self._entries.append(MigrationEntry(version, description, fn, database))

    def get_sorted(self) -> list[MigrationEntry]:
        return sorted(self._entries, key=lambda e: e.version)

    def get_for_database(self, database: str) -> list[MigrationEntry]:
        return sorted(
            [e for e in self._entries if e.database == database],
            key=lambda e: e.version,
        )

    @property
    def latest_version(self) -> int:
        return max(self._versions) if self._versions else 0

    @property
    def count(self) -> int:
        return len(self._entries)


_registry = MigrationRegistry()


def register_migration(version: int, description: str, fn: MigrationFn, *, database: str = 'state') -> None:
    _registry.register(version, description, fn, database=database)


def get_migrations() -> MigrationRegistry:
    return _registry


__all__ = ['MigrationRegistry', 'MigrationEntry', 'register_migration', 'get_migrations']
