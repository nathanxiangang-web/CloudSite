"""Persistence-neutral admin query views for Identity."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class IdentityStatsView:
    total: int
    legacy_seeded: int
    random_new: int
    rename_preserved: int
    move_preserved: int
    pending: int
    ambiguous: int
    manual_repairs: int

    def to_dict(self) -> dict[str, int]:
        return {
            "total": self.total,
            "legacy_seeded": self.legacy_seeded,
            "random_new": self.random_new,
            "rename_preserved": self.rename_preserved,
            "move_preserved": self.move_preserved,
            "pending": self.pending,
            "ambiguous": self.ambiguous,
            "manual_repairs": self.manual_repairs,
        }


@dataclass(frozen=True, slots=True)
class IdentityCandidateView:
    id: int
    cycle_id: int | None
    observed_path: str
    matched_resource_id: str | None
    candidate_resource_ids: list[str]
    match_type: str
    confidence: float
    status: str
    size: int
    modified_at: datetime | None
    extension: str
    mime_type: str
    fingerprint: str
    created_at: datetime
    resolved_at: datetime | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "cycle_id": self.cycle_id,
            "observed_path": self.observed_path,
            "matched_resource_id": self.matched_resource_id,
            "candidate_resource_ids": list(self.candidate_resource_ids),
            "match_type": self.match_type,
            "confidence": self.confidence,
            "status": self.status,
            "size": self.size,
            "modified_at": self.modified_at,
            "extension": self.extension,
            "mime_type": self.mime_type,
            "fingerprint": self.fingerprint,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
        }


__all__ = ["IdentityCandidateView", "IdentityStatsView"]
