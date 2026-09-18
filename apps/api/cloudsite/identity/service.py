import secrets
from datetime import datetime, timezone
from pathlib import PurePosixPath

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Folder, FolderIdentity, FolderIdentityHistory, OperationLog, Resource
from .schemas import FolderIdentityObservation, FolderIdentityResolution, IdentityObservation, IdentityResolution
from ..modules.identity.application.resource_resolution import (
    resolve_resource_identities as _resolve_resource_identities,
)
from ..modules.identity.infrastructure.resource_repository import (
    SqlAlchemyResourceIdentityRepository,
)
from ..modules.identity.domain.rules import (
    classify_identity_event,
    normalize_identity_path,
)


class _LegacyOperationLogAuditSink:
    """Adapter that keeps identity audit rows in the caller's state transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        *,
        level: str,
        action: str,
        message: str,
        created_at: datetime,
    ) -> None:
        self._session.add(
            OperationLog(
                level=level,
                module="identity",
                action=action,
                message=message,
                created_at=created_at,
            )
        )


# Transitional private aliases keep any legacy test/monkeypatch surface stable.
_normalize_path = normalize_identity_path
_event_type = classify_identity_event


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
    """Compatibility entry point backed by the Identity module application."""
    repository = SqlAlchemyResourceIdentityRepository(session)
    audit = _LegacyOperationLogAuditSink(session)
    return await _resolve_resource_identities(
        repository,
        audit,
        observations,
        visible_paths=visible_paths,
        cycle_id=cycle_id,
        allowed_candidate_paths=allowed_candidate_paths,
        defer_unseen_candidates=defer_unseen_candidates,
        now=now,
    )


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
