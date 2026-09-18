from datetime import datetime

from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Folder, OperationLog, Resource
from .schemas import FolderIdentityObservation, FolderIdentityResolution, IdentityObservation, IdentityResolution
from ..modules.identity.application.folder_resolution import (
    resolve_folder_identities as _resolve_folder_identities,
)
from ..modules.identity.application.resource_resolution import (
    resolve_resource_identities as _resolve_resource_identities,
)
from ..modules.identity.infrastructure.folder_repository import (
    SqlAlchemyFolderIdentityRepository,
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
    """Compatibility entry point; caller still owns the transaction commit."""
    repository = SqlAlchemyFolderIdentityRepository(session)
    return await _resolve_folder_identities(
        repository,
        observations,
        visible_paths=visible_paths,
        cycle_id=cycle_id,
        now=now,
    )


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
