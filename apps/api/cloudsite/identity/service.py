import secrets
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import OperationLog, ResourceIdentity, ResourceIdentityHistory
from .fingerprint import identity_fingerprint
from .schemas import IdentityObservation, IdentityResolution


TOUCH_INTERVAL = timedelta(hours=6)


def _normalize_path(value: str) -> str:
    parts = [part for part in str(value or "").replace("\\", "/").split("/") if part]
    return "/" + "/".join(parts) if parts else "/"


def _event_type(previous_path: str | None, current_path: str, previous_status: str) -> str:
    if previous_path is None:
        return "created"
    if previous_path == current_path:
        return "reactivated" if previous_status != "active" else "observed"
    if PurePosixPath(previous_path).parent == PurePosixPath(current_path).parent:
        return "rename"
    return "move"


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def _new_resource_id(session: AsyncSession, claimed: set[str]) -> str:
    while True:
        resource_id = "r_" + secrets.token_hex(16)
        if resource_id not in claimed and await session.get(ResourceIdentity, resource_id) is None:
            return resource_id


async def resolve_resource_identities(
    session: AsyncSession,
    observations: list[IdentityObservation],
    *,
    visible_paths: set[str],
    cycle_id: int | None = None,
    allowed_candidate_paths: set[str] | None = None,
    defer_unseen_candidates: bool = False,
    now: datetime | None = None,
) -> list[IdentityResolution]:
    """Resolve a complete batch conservatively and persist its identity registry changes.

    ``visible_paths`` distinguishes a copy (old path still exists) from a move.  Rolling
    scope callers additionally restrict fingerprint matching to missing paths in the
    current scope; this prevents a not-yet-scanned source path being guessed as a move.
    """
    now = now or datetime.now(timezone.utc)
    normalized_visible = {_normalize_path(path) for path in visible_paths}
    root_ids = {item.root_mapping_id for item in observations}
    statement = select(ResourceIdentity)
    if root_ids and None not in root_ids:
        statement = statement.where(ResourceIdentity.root_mapping_id.in_(root_ids))
    identities = list((await session.scalars(statement)).all())

    path_map: dict[str, ResourceIdentity] = {}
    fingerprint_map: dict[str, list[ResourceIdentity]] = defaultdict(list)
    for identity in identities:
        if identity.current_path:
            path = _normalize_path(identity.current_path)
            if path in path_map and path_map[path].resource_id != identity.resource_id:
                raise RuntimeError(f"多个 Stable ID 声明同一路径：{path}")
            path_map[path] = identity
        if identity.identity_fingerprint:
            fingerprint_map[identity.identity_fingerprint].append(identity)

    claimed: set[str] = set()
    resolutions: list[IdentityResolution] = []
    for raw in observations:
        observation = IdentityObservation(
            path=_normalize_path(raw.path),
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
            raise RuntimeError(f"同一 Stable ID 在一次扫描中被多个路径占用：{identity.resource_id}")

        if identity is None:
            unseen_candidates = [
                candidate
                for candidate in fingerprint_map.get(fingerprint, [])
                if candidate.resource_id not in claimed
                and candidate.current_path
                and _normalize_path(candidate.current_path) not in normalized_visible
            ]
            candidates = [
                candidate
                for candidate in unseen_candidates
                if allowed_candidate_paths is None
                or _normalize_path(candidate.current_path or "/") in allowed_candidate_paths
            ]
            if len(candidates) == 1:
                identity = candidates[0]
                match_type = "rename" if PurePosixPath(identity.current_path or "/").parent == PurePosixPath(observation.path).parent else "move"
            elif not candidates and defer_unseen_candidates and len(unseen_candidates) == 1:
                pending = unseen_candidates[0]
                resolutions.append(
                    IdentityResolution(
                        observation=observation,
                        resource_id=pending.resource_id,
                        match_type="pending_move_or_copy",
                        fingerprint=fingerprint,
                        previous_path=pending.current_path,
                    )
                )
                continue
            else:
                ambiguous_candidates = candidates or unseen_candidates
                if len(ambiguous_candidates) > 1:
                    ambiguous = sorted(candidate.resource_id for candidate in ambiguous_candidates)
                    match_type = "ambiguous_new"
                else:
                    match_type = "new"
                resource_id = await _new_resource_id(session, claimed)
                identity = ResourceIdentity(
                    resource_id=resource_id,
                    current_path=None,
                    root_mapping_id=observation.root_mapping_id,
                    status="active",
                    first_seen_at=now,
                    last_seen_at=now,
                    created_from="new_resource",
                    updated_at=now,
                )
                session.add(identity)
                identities.append(identity)
                fingerprint_map[fingerprint].append(identity)

        previous_path = identity.current_path
        previous_status = identity.status
        event_type = _event_type(previous_path, observation.path, previous_status)
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
        if event_type != "observed" or _utc(now) - _utc(identity.last_seen_at) >= TOUCH_INTERVAL:
            identity.last_seen_at = now
        if event_type != "observed":
            session.add(
                ResourceIdentityHistory(
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
            session.add(
                OperationLog(
                    level="INFO",
                    module="identity",
                    action=action,
                    message=f"Stable Resource ID {identity.resource_id}：{event_type}",
                    created_at=now,
                )
            )
        if ambiguous:
            session.add(
                OperationLog(
                    level="WARNING",
                    module="identity",
                    action="identity_candidate_ambiguous",
                    message=f"Stable ID 候选存在歧义：{len(ambiguous)} 个候选",
                    created_at=now,
                )
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
    await session.commit()
    return resolutions
