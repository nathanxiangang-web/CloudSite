"""Plugin contract — the narrow interface every CloudSite plugin implements."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from fastapi import APIRouter


@runtime_checkable
class Plugin(Protocol):
    """A pluggable feature module.

    Implementations must expose ``name`` and ``version`` as class-level or
    instance-level attributes and provide ``get_routers`` returning the
    FastAPI routers to mount on the host application.
    """

    name: str
    version: str

    def get_routers(self) -> list[APIRouter]: ...