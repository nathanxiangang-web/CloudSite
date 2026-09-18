import secrets
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Folder, FolderIdentity, FolderIdentityHistory, OperationLog, Resource, ResourceIdentity, ResourceIdentityHistory
from .fingerprint import identity_fingerprint
from .schemas import FolderIdentityObservation, FolderIdentityResolution, IdentityObservation, IdentityResolution
from ..modules.identity.application.matching import (
    ResourceIdentityCandidateView,
    choose_fingerprint_match,
)
from ..modules.identity.domain.rules import (
    classify_identity_event,
    normalize_identity_path,
)


TOUCH_INTERVAL = timedelta(hours=6)


# Transitional private aliases keep any legacy test/monkeypatch surface stable.
_normalize_path = normalize_identity_path
_event_type = classify_identity_event


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


async def resolve_folder_identities(
    session: AsyncSession,
    observations: list[FolderIdentityObservation],
    *,
    visible_paths: set[str],
    cycle_id: int | None = None,
    now: datetime | None = None,
) -> list[FolderIdentityResolution]:
    """Resolve folder identities: exact path → fingerprint match (highest score) → new."""
    now = now or datetime.now(timezone.utc)
    resolutions: list[FolderIdentityResolution] = []

    existing_by_path: dict[str, FolderIdentity] = {}
    existing_by_fingerprint: dict[str, list[FolderIdentity]] = {}
    for row in (await session.scalars(select(FolderIdentity).where(FolderIdentity.status.in_(("active", "suspected_missing"))))).all():
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
            claimed_ids.add(identity.folder_id)
            resolutions.append(FolderIdentityResolution(observation=obs, folder_id=identity.folder_id, match_type=match_type))
            continue

        # 严格匹配：空指纹不匹配；同 root 唯一候选才保留；多候选 ambiguous 按 new。
        candidates: list[FolderIdentity] = []
        if obs.fingerprint:
            candidates = [
                c for c in existing_by_fingerprint.get(obs.fingerprint, [])
                if c.folder_id not in claimed_ids
                and c.current_path not in visible_paths
                and c.root_mapping_id == obs.root_mapping_id
            ]
        if len(candidates) == 1:
            best = candidates[0]
            previous_path = best.current_path
            best.current_path = obs.path
            best.last_name = obs.name
            best.last_seen_at = now
            best.status = "active"
            claimed_ids.add(best.folder_id)
            event = "rename" if PurePosixPath(previous_path).parent == PurePosixPath(obs.path).parent else "move"
            session.add(FolderIdentityHistory(
                folder_id=best.folder_id, path=obs.path, event_type=event,
                from_path=previous_path, to_path=obs.path, cycle_id=cycle_id,
            ))
            resolutions.append(FolderIdentityResolution(observation=obs, folder_id=best.folder_id, match_type=event, previous_path=previous_path))
            continue

        folder_id = "f_" + secrets.token_hex(16)
        identity = FolderIdentity(
            folder_id=folder_id, current_path=obs.path, root_mapping_id=obs.root_mapping_id,
            status="active", last_name=obs.name, identity_fingerprint=obs.fingerprint,
            created_from="new_folder", first_seen_at=now, last_seen_at=now,
        )
        session.add(identity)
        session.add(FolderIdentityHistory(
            folder_id=folder_id, path=obs.path, event_type="created", cycle_id=cycle_id,
        ))
        claimed_ids.add(folder_id)
        match_type = "ambiguous" if len(candidates) > 1 else "created"
        resolutions.append(FolderIdentityResolution(observation=obs, folder_id=folder_id, match_type=match_type))

    return resolutions


async def cascade_rename_descendants(
    session: AsyncSession,
    folder_id: str,
    old_path_prefix: str,
    new_path_prefix: str,
    now: datetime | None = None,
) -> dict[str, int]:
    """Batch UPDATE path prefix for all descendants of a renamed folder.

    只替换开头前缀（substr 拼接新前缀 + 原后缀），LIKE 转义 %/\\/_ 避免
    通配符误匹配，不全局 replace 路径中后续同名片段（任务 C.6）。
    """
    old_seg = old_path_prefix.rstrip("/") + "/"
    new_seg = new_path_prefix.rstrip("/") + "/"
    escaped = old_seg.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    old_len = len(old_seg)
    folders_result = await session.execute(
        update(Folder)
        .where(Folder.path.like(escaped + "%", escape="\\"))
        .values(path=new_seg + func.substr(Folder.path, old_len + 1))
    )
    folders_count = folders_result.rowcount or 0
    resources_result = await session.execute(
        update(Resource)
        .where(Resource.path.like(escaped + "%", escape="\\"))
        .values(path=new_seg + func.substr(Resource.path, old_len + 1))
    )
    resources_count = resources_result.rowcount or 0
    return {"folders_updated": folders_count, "resources_updated": resources_count}
