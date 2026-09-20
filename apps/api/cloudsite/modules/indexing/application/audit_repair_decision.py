from __future__ import annotations

from dataclasses import dataclass

from ..domain.audit_diff import AuditDiffResult, AuditDiffType


@dataclass(slots=True)
class AuditRepairDecision:
    can_auto_repair: bool = False
    requires_manual_intervention: bool = False
    reason: str = ""
    repairable_entries: int = 0
    manual_entries: int = 0

    @property
    def should_repair(self) -> bool:
        return self.can_auto_repair and self.repairable_entries > 0


class AuditRepairDecider:
    def decide(self, diff: AuditDiffResult) -> AuditRepairDecision:
        if not diff.audit_completed:
            return AuditRepairDecision(can_auto_repair=False, reason="audit_not_completed")
        if diff.is_clean:
            return AuditRepairDecision(can_auto_repair=False, reason="no_discrepancies")
        counts = diff.count_by_type
        manual = counts.get(AuditDiffType.IDENTITY_CONFLICT, 0)
        auto = len(diff.entries) - manual
        if manual > 0 and auto == 0:
            return AuditRepairDecision(can_auto_repair=False, requires_manual_intervention=True, reason="all_entries_require_manual", manual_entries=manual)
        return AuditRepairDecision(can_auto_repair=True, requires_manual_intervention=manual > 0, reason="partial" if manual > 0 else "auto", repairable_entries=auto, manual_entries=manual)


__all__ = ["AuditRepairDecision", "AuditRepairDecider"]
