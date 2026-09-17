from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class InspectionRequest:
    resource_id: str
    provider_id: str
    category_id: str | None = None
    force_refresh: bool = False


@dataclass(slots=True)
class InspectionResult:
    resource_id: str
    provider_id: str
    path: str
    name: str
    size: int | None = None
    modified_at: datetime | None = None
    content_hash: str | None = None
    mime_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    identity_candidates: list[dict[str, Any]] = field(default_factory=list)
    inspected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    success: bool = True
    error_code: str | None = None
    error_message: str | None = None


__all__ = ['InspectionRequest', 'InspectionResult']