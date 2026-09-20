from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from ..domain.audit_diff import AuditDiffEntry, AuditDiffResult
from .audit_repair_decision import AuditRepairDecider, AuditRepairDecision


@dataclass(slots=True)
class AuditRepairResult:
    """Outcome of executing an audit repair."""

    decision: AuditRepairDecision
    repaired: list[AuditDiffEntry] = field(default_factory=list)
    skipped: list[AuditDiffEntry] = field(default_factory=list)
    failed: list[AuditDiffEntry] = field(default_factory=list)

    @property
    def total_repaired(self) -> int:
        return len(self.repaired)

    @property
    def total_failed(self) -> int:
        return len(self.failed)

    @property
    def success(self) -> bool:
        return self.decision.can_auto_repair and self.total_failed == 0


class AuditRepairExecutor:
    """Execute audit repair based on diff and decision (V2 §35-36).

    The repair function is injected so this service stays independent
    of the data layer.  Only auto-repairable entries are processed;
    identity_conflict entries are always skipped (manual intervention).
    """

    def __init__(self, decider: AuditRepairDecider | None = None) -> None:
        self._decider = decider or AuditRepairDecider()

    def execute(
        self,
        diff: AuditDiffResult,
        repair_fn: Callable[[AuditDiffEntry], bool],
    ) -> AuditRepairResult:
        decision = self._decider.decide(diff)
        result = AuditRepairResult(decision=decision)

        if not decision.should_repair:
            result.skipped = list(diff.entries)
            return result

        from ..domain.audit_diff import AuditDiffType
        for entry in diff.entries:
            if entry.diff_type is AuditDiffType.IDENTITY_CONFLICT:
                result.skipped.append(entry)
                continue
            ok = repair_fn(entry)
            if ok:
                result.repaired.append(entry)
            else:
                result.failed.append(entry)

        return result


__all__ = ["AuditRepairResult", "AuditRepairExecutor"]
