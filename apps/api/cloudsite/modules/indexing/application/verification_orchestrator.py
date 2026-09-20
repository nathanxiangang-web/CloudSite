from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from ..domain.verification_result import VerificationBatchResult, VerificationResult
from .verification_batch_selector import VerificationBatchSelector, VerificationCandidate


@dataclass(slots=True)
class VerificationOrchestrator:
    """Orchestrate rolling verification: select batch, compare fingerprints,
    collect results (V2 §32).

    The fingerprint comparison function is injected so this service stays
    independent of the provider adapter layer.
    """

    batch_selector: VerificationBatchSelector = field(default_factory=VerificationBatchSelector)

    def run(
        self,
        candidates: list[VerificationCandidate],
        fingerprint_compare: Callable[[VerificationCandidate], tuple[bool, int]],
        now: datetime | None = None,
    ) -> VerificationBatchResult:
        """Execute verification on a selected batch.

        fingerprint_compare returns (match: bool, child_count: int).
        """
        now = now or datetime.now(timezone.utc)
        batch = self.batch_selector.select(candidates, now=now)
        result = VerificationBatchResult()
        for candidate in batch:
            match, child_count = fingerprint_compare(candidate)
            result.add(VerificationResult(
                root_mapping_id=candidate.root_mapping_id,
                path=candidate.path,
                fingerprint_match=match,
                child_count=child_count,
                checked_at=now,
            ))
        return result


__all__ = ["VerificationOrchestrator"]
