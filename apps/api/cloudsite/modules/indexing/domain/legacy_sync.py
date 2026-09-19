"""Persistence-neutral views over the frozen legacy sync tables."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LegacySyncRunView:
    id: int
    status: str


@dataclass(frozen=True, slots=True)
class LegacySyncChangeView:
    id: int
    object_type: str
    object_id: str
    change_type: str


@dataclass(frozen=True, slots=True)
class LegacySyncChangePage:
    items: tuple[LegacySyncChangeView, ...]
    has_more: bool


__all__ = [
    "LegacySyncRunView",
    "LegacySyncChangeView",
    "LegacySyncChangePage",
]
