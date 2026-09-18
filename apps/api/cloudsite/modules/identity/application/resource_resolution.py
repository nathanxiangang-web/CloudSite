"""Resource stable-identity resolution application service."""

from __future__ import annotations

import secrets
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from .matching import ResourceIdentityCandidateView, choose_fingerprint_match
from .ports import IdentityAuditSink, ResourceIdentityRepository
from ..domain.fingerprint import identity_fingerprint
from ..domain.models import IdentityObservation, IdentityResolution
from ..domain.records import ResourceIdentityHistoryRecord, ResourceIdentityRecord
from ..domain.rules import classify_identity_event, normalize_identity_path


TOUCH_INTERVAL = timedelta(hours=6)


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def _new_resource_id(
    repository: ResourceIdentityRepository,
    claimed: set[str],
) -> str:
    while True:
        resource_id = "r_" + secrets.token_hex(16)
        if resource_id not in claimed and not await repository.id_exists(resource_id):
            return resource_id


async def resolve_resource_identities(
    repository: ResourceIdentityRepository,
    audit: IdentityAuditSink,
    observations: list[IdentityObservation],
    *,
    visible_paths: set[str],
    cycle_id: int | None = None,
    allowed_candidate_paths: set[str] | None = None,
    defer_unseen_candidates: bool = False,
    now: datetime | None = None,
) -> list[IdentityResolution]:
    """Resolve a complete resource batch and persist through application ports."""
    now = now or datetime.now(timezone.utc)
    normalized_visible = {
        normalize_identity_path(path) for path in visible_paths
    }
    root_ids = {item.root_mapping_id for item in observations}
    identities = await repository.list_for_roots(root_ids)

    path_map: dict[str, ResourceIdentityRecord] = {}
    fingerprint_map: dict[str, list[ResourceIdentityRecord]] = defaultdict(list)
    for identity in identities:
        if identity.current_path:
            path = normalize_identity_path(identity.current_path)
            if path in path_map and path_map[path].resource_id != identity.resource_id:
                raise RuntimeError(f"多个 Stable ID 声明同一路径：{path}")
            path_map[path] = identity
        if identity.identity_fingerprint:
            fingerprint_map[identity.identity_fingerprint].append(identity)

    claimed: set[str] = set()
    resolutions: list[IdentityResolution] = []

    for raw in observations:
        observation = IdentityObservation(
            path=normalize_identity_path(raw.path),
            name=raw.name,
            root_mapping_id=raw.root_mapping_id,
            size=max(0, int(raw.size)),
            modified_at=raw.modified_at,
            extension=str(raw.extension or "").lower().lstrip("."),
            mime_type=str(raw.mime_type or "application/octet-stream"),
            provider_object_id=raw.provider_object_id,
            content_hash=raw.content_hash,
        )
        fingerprint = identity_fingerprint(
            size=observation.size,
            modified_at=observation.modified_at,
            extension=observation.extension,
            mime_type=observation.mime_type,
        )

        identity = path_map.get(observation.path)
        match_type = "current_path"
        ambiguous: list[str] = []

        if identity and identity.resource_id in claimed:
            raise RuntimeError(
                f"同一 Stable ID 在一次扫描中被多个路径占用：{identity.resource_id}"
            )

        if identity is None:
            decision = choose_fingerprint_match(
                observation_path=observation.path,
                fingerprint_candidates=[
                    ResourceIdentityCandidateView(
                        resource_id=candidate.resource_id,
                        current_path=candidate.current_path,
                    )
                    for candidate in fingerprint_map.get(fingerprint, [])
                ],
                normalized_visible_paths=normalized_visible,
                claimed_resource_ids=claimed,
                allowed_candidate_paths=allowed_candidate_paths,
                defer_unseen_candidates=defer_unseen_candidates,
            )
            match_type = decision.match_type
            ambiguous = list(decision.ambiguous_resource_ids)

            if match_type in {"rename", "move"}:
                identity = next(
                    candidate
                    for candidate in fingerprint_map.get(fingerprint, [])
                    if candidate.resource_id == decision.resource_id
                )
            elif match_type == "pending_move_or_copy":
                resolutions.append(
                    IdentityResolution(
                        observation=observation,
                        resource_id=decision.resource_id or "",
                        match_type=match_type,
                        fingerprint=fingerprint,
                        previous_path=decision.previous_path,
                    )
                )
                continue
            else:
                resource_id = await _new_resource_id(repository, claimed)
                identity = ResourceIdentityRecord(
                    resource_id=resource_id,
                    current_path=None,
                    root_mapping_id=observation.root_mapping_id,
                    status="active",
                    first_seen_at=now,
                    last_seen_at=now,
                    created_from="new_resource",
                    updated_at=now,
                )
                await repository.add(identity)
                identities.append(identity)
                fingerprint_map[fingerprint].append(identity)

        previous_path = identity.current_path
        previous_status = identity.status
        event_type = classify_identity_event(
            previous_path, observation.path, previous_status
        )

        identity.current_path = observation.path
        identity.root_mapping_id = observation.root_mapping_id
        identity.status = "active"
        identity.last_name = observation.name
        identity.last_extension = observation.extension
        identity.last_mime_type = observation.mime_type
        identity.last_size = observation.size
        identity.last_modified_at = observation.modified_at
        identity.provider_object_id = observation.provider_object_id
        identity.content_hash = observation.content_hash
        identity.identity_fingerprint = fingerprint
        identity.fingerprint_version = 1
        identity.updated_at = now
        if (
            event_type != "observed"
            or _utc(now) - _utc(identity.last_seen_at) >= TOUCH_INTERVAL
        ):
            identity.last_seen_at = now

        await repository.save(identity)

        if event_type != "observed":
            await repository.add_history(
                ResourceIdentityHistoryRecord(
                    resource_id=identity.resource_id,
                    path=observation.path,
                    event_type=event_type,
                    first_observed_at=now,
                    last_observed_at=now,
                    from_path=previous_path if previous_path != observation.path else None,
                    to_path=observation.path,
                    cycle_id=cycle_id,
                    created_at=now,
                )
            )
            action = {
                "created": "identity_created",
                "rename": "identity_rename_detected",
                "move": "identity_move_detected",
                "reactivated": "identity_recovered",
            }.get(event_type, "identity_recovered")
            await audit.record(
                level="INFO",
                action=action,
                message=f"Stable Resource ID {identity.resource_id}：{event_type}",
                created_at=now,
            )

        if ambiguous:
            await audit.record(
                level="WARNING",
                action="identity_candidate_ambiguous",
                message=f"Stable ID 候选存在歧义：{len(ambiguous)} 个候选",
                created_at=now,
            )

        claimed.add(identity.resource_id)
        path_map[observation.path] = identity
        resolutions.append(
            IdentityResolution(
                observation=observation,
                resource_id=identity.resource_id,
                match_type=match_type,
                fingerprint=fingerprint,
                previous_path=previous_path,
                ambiguous_resource_ids=ambiguous,
            )
        )

    await repository.commit()
    return resolutions


__all__ = ["resolve_resource_identities"]
