"""Promote a completed durable scan into R8 verification baseline facts."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.directory_fingerprint import generate_fingerprint
from .durable_scan_repository import DurableScanRepository
from .verification_state_repository import VerificationStateRepository


def _entry_for_fingerprint(row: Any) -> dict[str, object]:
    metadata: dict[str, object] = {}
    raw = getattr(row, "metadata_json", None)
    if raw:
        try:
            decoded = json.loads(raw)
        except (TypeError, ValueError):
            decoded = {}
        if isinstance(decoded, dict):
            metadata = decoded

    return {
        "name": row.name,
        "is_dir": bool(row.is_dir),
        "size": row.size,
        "modified": row.modified,
        "provider_object_id": metadata.get("provider_object_id", ""),
    }


async def seed_verification_baseline_from_durable_run(
    session: AsyncSession,
    *,
    root_mapping_id: int,
    run_id: str,
    verified_at: str | None = None,
) -> int:
    """Replace one root's rolling-verification baseline from a completed run.

    The caller owns the transaction and must commit after this returns.
    Partial/failed/running scans are rejected so they can never become an
    authoritative verification baseline.
    """

    scans = DurableScanRepository(session)
    run = await scans.get_scan_run(run_id)
    if run is None:
        raise ValueError(f"durable scan run not found: {run_id}")
    if int(run.root_mapping_id) != int(root_mapping_id):
        raise ValueError(
            "durable scan root mismatch: "
            f"run={run.root_mapping_id} expected={root_mapping_id}"
        )
    if run.status != "completed":
        raise ValueError(
            f"durable scan run is not complete: id={run_id} status={run.status}"
        )

    dirs = await scans.list_dirs(run_id)
    unfinished = [row.path for row in dirs if row.status != "done"]
    if unfinished:
        raise ValueError(
            "completed durable run contains unfinished directories: "
            + ", ".join(unfinished[:5])
        )

    current_paths = {str(row.path) for row in dirs}
    entries = await scans.list_entries(run_id)
    grouped: dict[str, list[dict[str, object]]] = {
        path: [] for path in current_paths
    }
    for row in entries:
        dir_path = str(row.dir_path)
        if dir_path not in grouped:
            raise ValueError(
                f"durable staging entry references unknown dir: {dir_path}"
            )
        grouped[dir_path].append(_entry_for_fingerprint(row))

    verification = VerificationStateRepository(session)
    existing = {
        row.path: row
        for row in await verification.list_for_root(root_mapping_id)
    }

    for path in sorted(current_paths):
        fingerprint = generate_fingerprint(path, grouped[path])
        previous = existing.get(path)
        changed = bool(
            previous is not None
            and previous.fingerprint
            and previous.fingerprint != fingerprint.hash
        )
        await verification.mark_verified(
            root_mapping_id,
            path,
            fingerprint=fingerprint.hash,
            child_count=fingerprint.child_count,
            changed=changed,
            verified_at=verified_at,
        )

    for stale_path in sorted(set(existing) - current_paths):
        await verification.delete(root_mapping_id, stale_path)

    return len(current_paths)


__all__ = ["seed_verification_baseline_from_durable_run"]
