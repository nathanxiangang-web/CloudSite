from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class AuditDiffType(str, Enum):
    """Audit diff categories (V2 §36)."""

    MISSING_IN_PROVIDER = 'missing_in_provider'
    MISSING_IN_INDEX = 'missing_in_index'
    CHANGED = 'changed'
    IDENTITY_CONFLICT = 'identity_conflict'
    UNEXPECTED_PATH = 'unexpected_path'
    DUPLICATE_IDENTITY = 'duplicate_identity'


@dataclass(slots=True)
class AuditDiffEntry:
    """A single discrepancy found by full audit (V2 §36)."""

    diff_type: AuditDiffType
    root_mapping_id: int
    path: str
    is_dir: bool = False
    provider_object_id: str | None = None
    resource_id: str | None = None
    expected: dict[str, Any] | None = None
    actual: dict[str, Any] | None = None
    detected_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def is_missing_in_provider(self) -> bool:
        return self.diff_type is AuditDiffType.MISSING_IN_PROVIDER

    @property
    def is_missing_in_index(self) -> bool:
        return self.diff_type is AuditDiffType.MISSING_IN_INDEX

    @property
    def is_identity_conflict(self) -> bool:
        return self.diff_type is AuditDiffType.IDENTITY_CONFLICT

    @property
    def requires_repair(self) -> bool:
        """All diff types except identity_conflict can be auto-repaired
        when the audit itself completed successfully."""
        return self.diff_type is not AuditDiffType.IDENTITY_CONFLICT

    def to_dict(self) -> dict[str, str | int | bool | None]:
        return {
            'diff_type': self.diff_type.value,
            'root_mapping_id': self.root_mapping_id,
            'path': self.path,
            'is_dir': self.is_dir,
            'provider_object_id': self.provider_object_id,
            'resource_id': self.resource_id,
            'detected_at': self.detected_at.isoformat(),
        }


@dataclass(slots=True)
class AuditDiffResult:
    """Aggregated audit diff for a root or full audit run (V2 §35-36)."""

    root_mapping_id: int
    entries: list[AuditDiffEntry] = field(default_factory=list)
    audit_completed: bool = False

    @property
    def is_clean(self) -> bool:
        """True when audit completed and found no discrepancies."""
        return self.audit_completed and len(self.entries) == 0

    @property
    def count_by_type(self) -> dict[AuditDiffType, int]:
        counts: dict[AuditDiffType, int] = {t: 0 for t in AuditDiffType}
        for e in self.entries:
            counts[e.diff_type] = counts.get(e.diff_type, 0) + 1
        return counts

    def add(self, entry: AuditDiffEntry) -> None:
        self.entries.append(entry)

    def to_summary(self) -> dict[str, int | bool]:
        c = self.count_by_type
        return {
            'total': len(self.entries),
            'missing_in_provider': c[AuditDiffType.MISSING_IN_PROVIDER],
            'missing_in_index': c[AuditDiffType.MISSING_IN_INDEX],
            'changed': c[AuditDiffType.CHANGED],
            'identity_conflict': c[AuditDiffType.IDENTITY_CONFLICT],
            'unexpected_path': c[AuditDiffType.UNEXPECTED_PATH],
            'duplicate_identity': c[AuditDiffType.DUPLICATE_IDENTITY],
            'audit_completed': self.audit_completed,
            'is_clean': self.is_clean,
        }


__all__ = ['AuditDiffType', 'AuditDiffEntry', 'AuditDiffResult']