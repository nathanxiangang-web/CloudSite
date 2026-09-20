from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(slots=True)
class VerificationResult:
    """Result of verifying a single directory's fingerprint (V2 §32).

    After listing a directory and computing its fingerprint, compare with
    the stored fingerprint to determine if the directory is verified or
    dirty and needs re-scanning.
    """

    root_mapping_id: int
    path: str
    fingerprint_match: bool = True
    child_count: int = 0
    checked_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    previous_fingerprint: str | None = None
    current_fingerprint: str | None = None

    @property
    def is_verified(self) -> bool:
        """True when fingerprints match — directory is unchanged."""
        return self.fingerprint_match

    @property
    def is_dirty(self) -> bool:
        """True when fingerprints differ — directory needs re-scan."""
        return not self.fingerprint_match

    @property
    def has_previous_fingerprint(self) -> bool:
        return self.previous_fingerprint is not None

    def to_dict(self) -> dict[str, str | int | bool | None]:
        return {
            "root_mapping_id": self.root_mapping_id,
            "path": self.path,
            "fingerprint_match": self.fingerprint_match,
            "is_verified": self.is_verified,
            "is_dirty": self.is_dirty,
            "child_count": self.child_count,
            "checked_at": self.checked_at.isoformat(),
        }


@dataclass(slots=True)
class VerificationBatchResult:
    """Aggregated result of verifying a batch of directories (V2 §32)."""

    results: list[VerificationResult] = field(default_factory=list)

    def add(self, result: VerificationResult) -> None:
        self.results.append(result)

    @property
    def verified_count(self) -> int:
        return sum(1 for r in self.results if r.is_verified)

    @property
    def dirty_count(self) -> int:
        return sum(1 for r in self.results if r.is_dirty)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def dirty_paths(self) -> list[str]:
        """Paths that need targeted re-scanning."""
        return [r.path for r in self.results if r.is_dirty]

    def to_summary(self) -> dict[str, int | list[str]]:
        return {
            "total": self.total,
            "verified": self.verified_count,
            "dirty": self.dirty_count,
            "dirty_paths": self.dirty_paths,
        }


__all__ = ["VerificationResult", "VerificationBatchResult"]