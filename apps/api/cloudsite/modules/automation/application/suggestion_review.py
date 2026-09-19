"""Review, apply, reject, and revert Automation suggestions.

Automation owns suggestion lifecycle state. Approved writes and revision reads
cross into Catalog only through its public contract.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...catalog.contracts.public import (
    CatalogRevisionView,
    apply_automation_asset,
    apply_automation_new_entry,
    apply_automation_new_release,
    list_automation_revisions,
    revert_automation_target,
)
from ..infrastructure.models import CatalogSuggestion, utcnow

_KIND_NEW_ENTRY = "new_entry"
_KIND_NEW_RELEASE = "new_release"
_KIND_ASSET = "asset"
_KIND_CANDIDATE_DUPLICATE = "candidate_duplicate"
_KIND_CONFLICT = "conflict"


class SuggestionError(Exception):
    """Base error for suggestion review workflows."""


class SuggestionNotFound(SuggestionError):
    def __init__(self, suggestion_id: str):
        super().__init__(f"suggestion not found: {suggestion_id}")
        self.suggestion_id = suggestion_id


class SuggestionStateInvalid(SuggestionError):
    def __init__(self, suggestion_id: str, reason: str):
        super().__init__(f"suggestion {suggestion_id} state invalid: {reason}")
        self.suggestion_id = suggestion_id
        self.reason = reason


def _decode_json(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


@dataclass
class ApplyResult:
    suggestion_id: str
    success: bool
    error: str = ""
    entry_id: str | None = None
    release_id: str | None = None
    asset_id: str | None = None


@dataclass
class BatchApplyResult:
    results: list[ApplyResult] = field(default_factory=list)
    succeeded: int = 0
    failed: int = 0


async def get_suggestion(state: AsyncSession, suggestion_id: str) -> CatalogSuggestion:
    row = await state.get(CatalogSuggestion, suggestion_id)
    if row is None:
        raise SuggestionNotFound(suggestion_id)
    return row


async def list_suggestions(
    state: AsyncSession,
    *,
    suggestion_kind: str | None = None,
    status: str | None = None,
    target_entry_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[CatalogSuggestion], int]:
    stmt = select(CatalogSuggestion).order_by(
        CatalogSuggestion.created_at, CatalogSuggestion.suggestion_id
    )
    count_stmt = select(func.count()).select_from(CatalogSuggestion)
    if suggestion_kind is not None:
        stmt = stmt.where(CatalogSuggestion.suggestion_kind == suggestion_kind)
        count_stmt = count_stmt.where(
            CatalogSuggestion.suggestion_kind == suggestion_kind
        )
    if status is not None:
        stmt = stmt.where(CatalogSuggestion.status == status)
        count_stmt = count_stmt.where(CatalogSuggestion.status == status)
    if target_entry_id is not None:
        stmt = stmt.where(CatalogSuggestion.target_entry_id == target_entry_id)
        count_stmt = count_stmt.where(
            CatalogSuggestion.target_entry_id == target_entry_id
        )
    stmt = stmt.limit(max(int(limit), 0)).offset(max(int(offset), 0))
    rows = list((await state.scalars(stmt)).all())
    total = int(await state.scalar(count_stmt) or 0)
    return rows, total


async def _apply_new_entry(
    state: AsyncSession,
    index: AsyncSession,
    suggestion: CatalogSuggestion,
    actor: str,
) -> ApplyResult:
    fields = _decode_json(suggestion.suggested_fields_json)
    applied = await apply_automation_new_entry(
        state,
        index,
        source_resource_id=suggestion.source_file_id,
        fields=fields,
        actor=actor,
    )
    suggestion.target_entry_id = applied.entry_id
    suggestion.target_release_id = applied.release_id
    suggestion.target_asset_id = applied.asset_id
    suggestion.applied_revision_id = applied.revision_id
    return ApplyResult(
        suggestion_id=suggestion.suggestion_id,
        success=True,
        entry_id=applied.entry_id,
        release_id=applied.release_id,
        asset_id=applied.asset_id,
    )


async def _apply_new_release(
    state: AsyncSession,
    suggestion: CatalogSuggestion,
    actor: str,
) -> ApplyResult:
    fields = _decode_json(suggestion.suggested_fields_json)
    entry_id = suggestion.target_entry_id or fields.get("entry_id")
    if not entry_id:
        raise SuggestionStateInvalid(
            suggestion.suggestion_id, "缺少 target_entry_id"
        )
    applied = await apply_automation_new_release(
        state,
        entry_id=entry_id,
        fields=fields,
        actor=actor,
    )
    suggestion.target_release_id = applied.release_id
    suggestion.applied_revision_id = applied.revision_id
    return ApplyResult(
        suggestion_id=suggestion.suggestion_id,
        success=True,
        entry_id=entry_id,
        release_id=applied.release_id,
    )


async def _apply_asset(
    state: AsyncSession,
    suggestion: CatalogSuggestion,
    actor: str,
) -> ApplyResult:
    fields = _decode_json(suggestion.suggested_fields_json)
    release_id = suggestion.target_release_id or fields.get("release_id")
    if not release_id:
        raise SuggestionStateInvalid(
            suggestion.suggestion_id, "缺少 target_release_id"
        )
    applied = await apply_automation_asset(
        state,
        release_id=release_id,
        source_resource_id=suggestion.source_file_id,
        fields=fields,
        actor=actor,
    )
    suggestion.target_asset_id = applied.asset_id
    suggestion.applied_revision_id = applied.revision_id
    return ApplyResult(
        suggestion_id=suggestion.suggestion_id,
        success=True,
        release_id=release_id,
        asset_id=applied.asset_id,
    )


async def apply_suggestion(
    state: AsyncSession,
    index: AsyncSession,
    suggestion_id: str,
    *,
    actor: str = "admin",
) -> ApplyResult:
    suggestion = await get_suggestion(state, suggestion_id)
    if suggestion.status == "applied":
        return ApplyResult(
            suggestion_id=suggestion_id,
            success=True,
            entry_id=suggestion.target_entry_id,
            release_id=suggestion.target_release_id,
            asset_id=suggestion.target_asset_id,
        )
    if suggestion.status == "rejected":
        raise SuggestionStateInvalid(
            suggestion_id, "已拒绝的建议不能 apply"
        )

    kind = suggestion.suggestion_kind
    if kind == _KIND_NEW_ENTRY:
        result = await _apply_new_entry(state, index, suggestion, actor)
    elif kind == _KIND_NEW_RELEASE:
        result = await _apply_new_release(state, suggestion, actor)
    elif kind == _KIND_ASSET:
        result = await _apply_asset(state, suggestion, actor)
    elif kind in (_KIND_CANDIDATE_DUPLICATE, _KIND_CONFLICT):
        result = ApplyResult(suggestion_id=suggestion_id, success=True)
    else:
        raise SuggestionStateInvalid(
            suggestion_id, f"未知建议类型: {kind}"
        )

    suggestion.status = "applied"
    suggestion.reviewed_by = actor
    suggestion.reviewed_at = utcnow()
    suggestion.applied_at = utcnow()
    await state.flush()
    return result


async def reject_suggestion(
    state: AsyncSession,
    suggestion_id: str,
    *,
    actor: str = "admin",
    reason: str = "",
) -> CatalogSuggestion:
    suggestion = await get_suggestion(state, suggestion_id)
    if suggestion.status == "rejected":
        return suggestion
    if suggestion.status == "applied":
        raise SuggestionStateInvalid(
            suggestion_id, "已应用的建议不能拒绝，请先撤销"
        )
    suggestion.status = "rejected"
    suggestion.reviewed_by = actor
    suggestion.reviewed_at = utcnow()
    suggestion.reject_reason = reason
    await state.flush()
    return suggestion


async def batch_apply_suggestions(
    state: AsyncSession,
    index: AsyncSession,
    suggestion_ids: list[str],
    *,
    actor: str = "admin",
) -> BatchApplyResult:
    result = BatchApplyResult()
    for sid in suggestion_ids:
        try:
            single = await apply_suggestion(
                state, index, sid, actor=actor
            )
            result.results.append(single)
            result.succeeded += 1
        except Exception as exc:
            result.results.append(
                ApplyResult(
                    suggestion_id=sid,
                    success=False,
                    error=str(exc),
                )
            )
            result.failed += 1
    return result


async def batch_reject_suggestions(
    state: AsyncSession,
    suggestion_ids: list[str],
    *,
    actor: str = "admin",
    reason: str = "",
) -> BatchApplyResult:
    result = BatchApplyResult()
    for sid in suggestion_ids:
        try:
            await reject_suggestion(
                state, sid, actor=actor, reason=reason
            )
            result.results.append(
                ApplyResult(suggestion_id=sid, success=True)
            )
            result.succeeded += 1
        except Exception as exc:
            result.results.append(
                ApplyResult(
                    suggestion_id=sid,
                    success=False,
                    error=str(exc),
                )
            )
            result.failed += 1
    return result


async def revert_suggestion(
    state: AsyncSession,
    suggestion_id: str,
    *,
    actor: str = "admin",
) -> CatalogSuggestion:
    suggestion = await get_suggestion(state, suggestion_id)
    if suggestion.status != "applied":
        raise SuggestionStateInvalid(
            suggestion_id, "仅已应用的建议可撤销"
        )

    kind = suggestion.suggestion_kind
    if kind == _KIND_NEW_ENTRY and suggestion.target_entry_id:
        await revert_automation_target(
            state,
            target_type="entry",
            target_id=suggestion.target_entry_id,
            actor=actor,
        )
    elif kind == _KIND_NEW_RELEASE and suggestion.target_release_id:
        await revert_automation_target(
            state,
            target_type="release",
            target_id=suggestion.target_release_id,
            actor=actor,
        )
    elif kind == _KIND_ASSET and suggestion.target_asset_id:
        await revert_automation_target(
            state,
            target_type="asset",
            target_id=suggestion.target_asset_id,
            actor=actor,
        )

    suggestion.status = "reviewed"
    suggestion.applied_at = None
    await state.flush()
    return suggestion


async def list_suggestion_revisions(
    state: AsyncSession,
    suggestion_id: str,
    *,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[CatalogRevisionView], int]:
    suggestion = await get_suggestion(state, suggestion_id)
    targets: list[tuple[str, str]] = []
    if suggestion.target_entry_id:
        targets.append(("entry", suggestion.target_entry_id))
    if suggestion.target_release_id:
        targets.append(("release", suggestion.target_release_id))
    if suggestion.target_asset_id:
        targets.append(("asset", suggestion.target_asset_id))
    return await list_automation_revisions(
        state,
        targets=targets,
        limit=limit,
        offset=offset,
    )
