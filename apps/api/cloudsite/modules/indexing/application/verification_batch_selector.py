from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import IntEnum


class VerificationPriority(IntEnum):
    """Priority rank for directory verification selection (V2 §33).

    Lower number = higher priority.
    """

    PREVIOUSLY_FAILED = 0
    LONG_UNVERIFIED = 1
    HIGH_RISK = 2
    RECENTLY_CHANGED = 3
    TOP_LEVEL = 4
    NORMAL = 5
    RECENTLY_ACTIVE = 6


@dataclass(slots=True)
class VerificationCandidate:
    """A directory eligible for rolling verification."""

    root_mapping_id: int
    path: str
    depth: int = 0
    last_verified_at: datetime | None = None
    last_changed_at: datetime | None = None
    is_high_risk: bool = False
    previously_failed: bool = False
    verification_priority: int = 0

    def compute_priority(self, now: datetime | None = None) -> int:
        """Compute and set the verification priority rank."""
        now = now or datetime.now(timezone.utc)
        if self.previously_failed:
            self.verification_priority = VerificationPriority.PREVIOUSLY_FAILED
        elif self.last_verified_at is None or (now - self.last_verified_at) > timedelta(days=30):
            # Coverage must be starvation-safe: a never/long-unverified
            # directory outranks permanently "important" paths such as
            # top-level directories.
            self.verification_priority = VerificationPriority.LONG_UNVERIFIED
        elif self.is_high_risk:
            self.verification_priority = VerificationPriority.HIGH_RISK
        elif self.last_changed_at and (now - self.last_changed_at) < timedelta(hours=24):
            self.verification_priority = VerificationPriority.RECENTLY_CHANGED
        elif (
            self.depth <= 1
            and self.last_verified_at
            and (now - self.last_verified_at) > timedelta(days=1)
        ):
            # Top-level paths get a daily boost, not a permanent one. Once
            # checked they rejoin normal rotation so deeper paths still move.
            self.verification_priority = VerificationPriority.TOP_LEVEL
        elif self.last_verified_at and (now - self.last_verified_at) < timedelta(days=7):
            # Recently verified paths stay eligible but deliberately rank
            # below older normal paths so the batch rotates.
            self.verification_priority = VerificationPriority.RECENTLY_ACTIVE
        else:
            self.verification_priority = VerificationPriority.NORMAL
        return self.verification_priority


class VerificationBatchSelector:
    """Select a batch of directories for rolling verification (V2 §32-33).

    Orders candidates by priority then picks the top *batch_size*.
    Deterministic: same input always yields same output.
    """

    def __init__(self, batch_size: int = 50) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        self.batch_size = batch_size

    def select(
        self,
        candidates: list[VerificationCandidate],
        now: datetime | None = None,
    ) -> list[VerificationCandidate]:
        """Return up to *batch_size* candidates ordered by priority then path."""
        now = now or datetime.now(timezone.utc)
        for c in candidates:
            c.compute_priority(now)
        def _last_verified_key(candidate: VerificationCandidate) -> float:
            if candidate.last_verified_at is None:
                return float("-inf")
            return candidate.last_verified_at.timestamp()

        ranked = sorted(
            candidates,
            key=lambda c: (
                c.verification_priority,
                _last_verified_key(c),
                c.depth,
                c.path,
            ),
        )
        return ranked[: self.batch_size]


__all__ = [
    'VerificationPriority',
    'VerificationCandidate',
    'VerificationBatchSelector',
]