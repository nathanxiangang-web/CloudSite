"""Folder stable-identity resolution application service."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from pathlib import PurePosixPath

from .ports import FolderIdentityRepository
from ..domain.models import FolderIdentityObservation, FolderIdentityResolution
from ..domain.records import FolderIdentityHistoryRecord, FolderIdentityRecord


async def resolve_folder_identities(
    repository: FolderIdentityRepository,
    observations: list[FolderIdentityObservation],
    *,
    visible_paths: set[str],
    cycle_id: int | None = None,
    now: datetime | None = None,
) -> list[FolderIdentityResolution]:
    """Resolve folder identities without committing the caller transaction."""
    now = now or datetime.now(timezone.utc)
    resolutions: list[FolderIdentityResolution] = []

    existing_by_path: dict[str, FolderIdentityRecord] = {}
    existing_by_fingerprint: dict[str, list[FolderIdentityRecord]] = {}
    for row in await repository.list_active():
        existing_by_path[row.current_path] = row
        if row.identity_fingerprint:
            existing_by_fingerprint.setdefault(row.identity_fingerprint, []).append(row)

    claimed_ids: set[str] = set()
    for obs in observations:
        identity = existing_by_path.get(obs.path)
        if identity:
            match_type = "observed" if identity.status == "active" else "reactivated"
            identity.last_seen_at = now
            identity.last_name = obs.name
            identity.identity_fingerprint = obs.fingerprint
            identity.status = "active"
            await repository.save(identity)
            claimed_ids.add(identity.folder_id)
            resolutions.append(
                FolderIdentityResolution(
                    observation=obs,
                    folder_id=identity.folder_id,
                    match_type=match_type,
                )
            )
            continue

        candidates: list[FolderIdentityRecord] = []
        if obs.fingerprint:
            candidates = [
                candidate
                for candidate in existing_by_fingerprint.get(obs.fingerprint, [])
                if candidate.folder_id not in claimed_ids
                and candidate.current_path not in visible_paths
                and candidate.root_mapping_id == obs.root_mapping_id
            ]

        if len(candidates) == 1:
            best = candidates[0]
            previous_path = best.current_path
            best.current_path = obs.path
            best.last_name = obs.name
            best.last_seen_at = now
            best.status = "active"
            await repository.save(best)
            claimed_ids.add(best.folder_id)
            event = (
                "rename"
                if PurePosixPath(previous_path).parent == PurePosixPath(obs.path).parent
                else "move"
            )
            await repository.add_history(
                FolderIdentityHistoryRecord(
                    folder_id=best.folder_id,
                    path=obs.path,
                    event_type=event,
                    from_path=previous_path,
                    to_path=obs.path,
                    cycle_id=cycle_id,
                )
            )
            resolutions.append(
                FolderIdentityResolution(
                    observation=obs,
                    folder_id=best.folder_id,
                    match_type=event,
                    previous_path=previous_path,
                )
            )
            continue

        folder_id = "f_" + secrets.token_hex(16)
        identity = FolderIdentityRecord(
            folder_id=folder_id,
            current_path=obs.path,
            root_mapping_id=obs.root_mapping_id,
            status="active",
            first_seen_at=now,
            last_seen_at=now,
            last_name=obs.name,
            identity_fingerprint=obs.fingerprint,
            created_from="new_folder",
            updated_at=now,
        )
        await repository.add(identity)
        await repository.add_history(
            FolderIdentityHistoryRecord(
                folder_id=folder_id,
                path=obs.path,
                event_type="created",
                cycle_id=cycle_id,
            )
        )
        claimed_ids.add(folder_id)
        match_type = "ambiguous" if len(candidates) > 1 else "created"
        resolutions.append(
            FolderIdentityResolution(
                observation=obs,
                folder_id=folder_id,
                match_type=match_type,
            )
        )

    return resolutions


__all__ = ["resolve_folder_identities"]
