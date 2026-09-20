"""Identity matching engine for stable resource_id preservation (V2 doc 22-23).

Provides provider-stable identity fingerprints and a matching engine that
preserves resource_id across file rename/move and subtree path updates within
the same content root. Cross-root moves are explicitly NOT supported:
identity is scoped to root_mapping_id, so a move across roots yields no_match
and a new resource_id is allocated.

The matching digest is computed from size + modified_at + root_mapping_id
only. It is intentionally path- and name-independent so that rename (name
change) and move (path change) within the same root preserve identity. The
``IdentityFingerprint`` dataclass still carries ``name`` and ``path`` for
history recording and human inspection, but they do not participate in the
digest.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable


def _normalized_time(value: datetime | None) -> str:
    if value is None:
        return ""
    normalized = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return normalized.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if hasattr(obj, key):
        return getattr(obj, key)
    if isinstance(obj, dict):
        return obj.get(key, default)
    return default


@dataclass(frozen=True, slots=True)
class IdentityFingerprint:
    """Provider-stable object identity fingerprint.

    Carries name + size + modified_at + root_mapping_id + path. The matching
    ``digest`` is computed from size + modified_at + root_mapping_id only
    (path- and name-independent) so rename and move within the same root
    preserve identity. Cross-root moves change root_mapping_id and therefore
    yield a different digest (no match -> new id), which is the explicitly
    unsupported case.
    """

    name: str
    size: int | None
    modified_at: datetime | None
    root_mapping_id: int
    path: str | None = None

    @property
    def digest(self) -> str:
        payload = "|".join(
            (
                "v1",
                str(self.root_mapping_id),
                "" if self.size is None else str(max(0, int(self.size))),
                _normalized_time(self.modified_at),
            )
        )
        return hashlib.blake2s(payload.encode("utf-8")).hexdigest()

    def matches(self, other: "IdentityFingerprint") -> bool:
        return self.digest == other.digest


@dataclass(frozen=True, slots=True)
class IdentityRecord:
    """A persisted identity history record."""

    resource_id: str
    fingerprint: str
    root_mapping_id: int
    name: str
    path: str | None
    size: int | None
    modified_at: datetime | None
    first_seen_at: datetime
    last_seen_at: datetime
    status: str = "active"


@dataclass(frozen=True, slots=True)
class IdentityMatchResult:
    """Result of matching a fingerprint against identity history.

    match_type is one of:
      - "matched": exactly one history record shares the digest; resource_id
        is the preserved id.
      - "conflict": two or more history records share the digest; the engine
        never silently picks one. conflicting_ids lists all candidates.
      - "no_match": no history record shares the digest; a new identity
        should be allocated.
    """

    match_type: str
    resource_id: str | None = None
    conflicting_ids: tuple[str, ...] = ()
    previous_path: str | None = None
    fingerprint: str | None = None

    @property
    def is_matched(self) -> bool:
        return self.match_type == "matched"

    @property
    def is_conflict(self) -> bool:
        return self.match_type == "conflict"

    @property
    def is_new(self) -> bool:
        return self.match_type == "no_match"


class IdentityMatchingEngine:
    """Provider-stable identity matching engine.

    Same fingerprint digest -> same resource_id. Multiple matches -> conflict
    (never silently matched). No match -> no_match (new identity). Identity is
    scoped to root_mapping_id; cross-root moves are not supported and yield
    no_match.
    """

    def extract_fingerprint(self, entry: Any) -> IdentityFingerprint:
        """Extract a stable fingerprint from a provider entry.

        Accepts a SnapshotEntry, dataclass, or mapping-like object exposing
        ``name`` / ``size`` / ``modified_at`` / ``root_mapping_id`` / ``path``
        via attributes or keys. Missing ``root_mapping_id`` defaults to 0.
        """
        return IdentityFingerprint(
            name=str(_get(entry, "name", "") or ""),
            size=_get(entry, "size", None),
            modified_at=_get(entry, "modified_at", None),
            root_mapping_id=int(_get(entry, "root_mapping_id", 0) or 0),
            path=_get(entry, "path", None),
        )

    def match(
        self,
        fingerprint: IdentityFingerprint,
        history: Iterable[IdentityRecord],
    ) -> IdentityMatchResult:
        """Match a fingerprint against identity history.

        Candidates are history records in the same root with the same digest.
        Zero candidates -> no_match. One -> matched. More than one -> conflict.
        """
        candidates = [
            rec
            for rec in history
            if rec.root_mapping_id == fingerprint.root_mapping_id
            and rec.fingerprint == fingerprint.digest
        ]
        if not candidates:
            return IdentityMatchResult(
                match_type="no_match",
                fingerprint=fingerprint.digest,
            )
        if len(candidates) == 1:
            rec = candidates[0]
            return IdentityMatchResult(
                match_type="matched",
                resource_id=rec.resource_id,
                previous_path=rec.path,
                fingerprint=fingerprint.digest,
            )
        return IdentityMatchResult(
            match_type="conflict",
            conflicting_ids=tuple(sorted(c.resource_id for c in candidates)),
            fingerprint=fingerprint.digest,
        )

    def record_history(
        self,
        resource_id: str,
        fingerprint: IdentityFingerprint,
        *,
        now: datetime | None = None,
    ) -> IdentityRecord:
        """Build an identity history record for persistence.

        Returns the built record; persistence is performed by the
        IdentityRepository. This method is pure and does not touch the DB.
        """
        ts = now or datetime.now(timezone.utc)
        return IdentityRecord(
            resource_id=resource_id,
            fingerprint=fingerprint.digest,
            root_mapping_id=fingerprint.root_mapping_id,
            name=fingerprint.name,
            path=fingerprint.path,
            size=fingerprint.size,
            modified_at=fingerprint.modified_at,
            first_seen_at=ts,
            last_seen_at=ts,
            status="active",
        )


__all__ = [
    "IdentityFingerprint",
    "IdentityRecord",
    "IdentityMatchResult",
    "IdentityMatchingEngine",
]
