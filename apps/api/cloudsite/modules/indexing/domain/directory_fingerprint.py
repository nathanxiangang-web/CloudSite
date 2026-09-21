"""R6 PR03: Directory Fingerprint (V2 doc section 31).

A directory fingerprint is a lightweight stable hash over the directory's
child entries, used by Rolling Verification to detect changes without
re-hashing file contents. The fingerprint is order-independent: entries are
sorted by name before hashing so that two listings of the same directory
produce the same fingerprint regardless of enumeration order.

Each entry contributes: name, is_dir, size, modified, and (optional)
provider_object_id. Missing provider_object_id values are normalized to an
empty string so that entries without a provider object id produce a stable
fingerprint.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(slots=True)
class DirectoryFingerprint:
    """Directory fingerprint: stable hash over sorted child entries."""

    path: str
    hash: str
    child_count: int
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


def _entry_signature(entry: dict) -> tuple:
    """Build the hashable signature tuple for a single entry.

    Fields are normalized so that missing optional values do not destabilize
    the fingerprint:
      - name is required and used as the sort key
      - is_dir defaults to False
      - size defaults to 0
      - modified defaults to empty string
      - provider_object_id defaults to empty string
    """
    name = entry.get("name")
    if name is None:
        raise ValueError("entry is missing required field 'name'")
    is_dir = bool(entry.get("is_dir", False))
    size = entry.get("size", 0)
    if size is None:
        size = 0
    modified = entry.get("modified", "")
    if modified is None:
        modified = ""
    elif isinstance(modified, datetime):
        if modified.tzinfo is None:
            modified = modified.replace(tzinfo=timezone.utc)
        modified = modified.astimezone(timezone.utc).isoformat()
    elif isinstance(modified, str) and modified:
        try:
            parsed = datetime.fromisoformat(modified.replace("Z", "+00:00"))
        except ValueError:
            modified = modified.strip()
        else:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            modified = parsed.astimezone(timezone.utc).isoformat()
    provider_object_id = entry.get("provider_object_id", "")
    if provider_object_id is None:
        provider_object_id = ""
    return (str(name), is_dir, int(size), str(modified), str(provider_object_id))


def generate_fingerprint(path: str, entries: list[dict]) -> DirectoryFingerprint:
    """Generate a directory fingerprint from a list of child entries.

    Entries are sorted by name before hashing, so the resulting fingerprint
    is independent of the input enumeration order. SHA-256 is used as the
    hash algorithm.
    """
    signatures = [_entry_signature(e) for e in entries]
    signatures.sort(key=lambda sig: sig[0])
    payload = json.dumps(signatures, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return DirectoryFingerprint(
        path=path,
        hash=digest,
        child_count=len(entries),
    )


def compare_fingerprints(
    current: DirectoryFingerprint, stored: DirectoryFingerprint
) -> bool:
    """Return True when two fingerprints are consistent.

    Two fingerprints match when both their hash and child_count agree. The
    path is intentionally excluded from the comparison so that a directory
    moved to a new path with identical contents still compares equal when
    the caller explicitly passes both fingerprints.
    """
    return current.hash == stored.hash and current.child_count == stored.child_count


__all__ = [
    "DirectoryFingerprint",
    "generate_fingerprint",
    "compare_fingerprints",
]
