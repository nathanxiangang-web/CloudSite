"""Persistence-neutral legacy sync views used by downstream automation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ParserSeedRunView:
    id: int
    status: str


@dataclass(frozen=True, slots=True)
class ParserSeedChangeView:
    id: int
    object_type: str
    object_id: str
    change_type: str


__all__ = ["ParserSeedRunView", "ParserSeedChangeView"]
