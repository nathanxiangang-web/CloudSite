"""Scan configuration fingerprint (V2 doc sections 17, 60).

A ``ScanFingerprint`` captures the configuration that produced a scan run:
connection_id, root_mapping_id, storage_path, adapter_version, and
scan_schema_version. Every scan run persists its fingerprint; when any key
field changes, previously stored runs are considered incompatible and must
not be resumed (V2 section 17). This prevents restoring a stale run whose
results were produced under a different connection, storage layout, or
adapter/schema version, which would yield an inconsistent index.

The fingerprint is intentionally a plain value object: compatibility is
exact field-by-field equality. There is no partial match, no version skew
tolerance, and no silent inheritance -- any single field difference makes
two fingerprints incompatible.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields


@dataclass(frozen=True, slots=True)
class ScanFingerprint:
    """Configuration fingerprint for a scan run (V2 sections 17, 60).

    Two fingerprints are compatible iff every field matches exactly. The
    fields are the minimal set that determines whether a previously stored
    scan run's results are still valid for the current configuration:

    - connection_id: the AList connection the scan read from
    - root_mapping_id: the content root being indexed
    - storage_path: the provider storage path / mount root
    - adapter_version: the adapter implementation version
    - scan_schema_version: the scan result schema version
    """

    connection_id: int
    root_mapping_id: int
    storage_path: str
    adapter_version: str
    scan_schema_version: int

    def to_dict(self) -> dict:
        """Return a JSON-serializable dict with stable key order."""
        return {
            "connection_id": self.connection_id,
            "root_mapping_id": self.root_mapping_id,
            "storage_path": self.storage_path,
            "adapter_version": self.adapter_version,
            "scan_schema_version": self.scan_schema_version,
        }

    def is_compatible(self, other: "ScanFingerprint") -> bool:
        """Return True iff every fingerprint field matches exactly."""
        if not isinstance(other, ScanFingerprint):
            return NotImplemented  # type: ignore[return-value]
        return self.to_dict() == other.to_dict()


def generate_fingerprint(
    connection_id: int,
    root_mapping_id: int,
    storage_path: str,
    adapter_version: str,
    scan_schema_version: int,
) -> ScanFingerprint:
    """Build a ScanFingerprint from the current scan configuration."""
    return ScanFingerprint(
        connection_id=connection_id,
        root_mapping_id=root_mapping_id,
        storage_path=storage_path,
        adapter_version=adapter_version,
        scan_schema_version=scan_schema_version,
    )


__all__ = ["ScanFingerprint", "generate_fingerprint"]
