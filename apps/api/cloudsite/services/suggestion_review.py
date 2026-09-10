"""A2 审核服务：apply/reject/撤销建议，事务化、幂等、批量逐项返回。

apply 在同一 state 事务内修改正式 catalog 内容并写入 catalog_revisions /
catalog_search_outbox（由 catalog 服务内部完成），随后更新 suggestion 状态。
幂等：已 applied 的建议重复 apply 直接返回，不重复修改正式内容；已 rejected
的建议重复 reject 直接返回。批量操作逐项独立 try/except，单项失败不阻塞其他
项，也不伪装全批成功。撤销作用于内容归组/编辑，产生新修订（archive/disable），
不删除底层文件，不破坏既有身份。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import CatalogRevision, CatalogSuggestion, utcnow
from . import catalog as catalog_service
from .catalog_metadata import append_catalog_revision

_KIND_NEW_ENTRY = "new_entry"
_KIND_NEW_RELEASE = "new_release"
_KIND_ASSET = "asset"
_KIND_CANDIDATE_DUPLICATE = "candidate_duplicate"
_KIND_CONFLICT = "conflict"


class SuggestionError(Exception):
    """建议审核服务错误基类。"""


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
    """分页筛选建议列表。返回 (rows, total)。"""
    stmt = select(CatalogSuggestion).order_by(
        CatalogSuggestion.created_at, CatalogSuggestion.suggestion_id
    )
    count_stmt = select(func.count()).select_from(CatalogSuggestion)
    if suggestion_kind is not None:
        stmt = stmt.where(CatalogSuggestion.suggestion_kind == suggestion_kind)
        count_stmt = count_stmt.where(CatalogSuggestion.suggestion_kind == suggestion_kind)
    if status is not None:
        stmt = stmt.where(CatalogSuggestion.status == status)
        count_stmt = count_stmt.where(CatalogSuggestion.status == status)
    if target_entry_id is not None:
        stmt = stmt.where(CatalogSuggestion.target_entry_id == target_entry_id)
        count_stmt = count_stmt.where(CatalogSuggestion.target_entry_id == target_entry_id)
    stmt = stmt.limit(max(int(limit), 0)).offset(max(int(offset), 0))
    rows = list((await state.scalars(stmt)).all())
    total = int(await state.scalar(count_stmt) or 0)
    return rows, total


async def _latest_revision_id(
    state: AsyncSession, target_type: str, target_id: str
) -> str | None:
    row = await state.scalar(
        select(CatalogRevision)
        .where(
            CatalogRevision.target_type == target_type,
            CatalogRevision.target_id == target_id,
        )
        .order_by(CatalogRevision.created_at.desc())
    )
    return row.revision_id if row is not None else None


async def _apply_new_entry(
    state: AsyncSession, index: AsyncSession, suggestion: CatalogSuggestion, actor: str
) -> ApplyResult:
    fields = _decode_json(suggestion.suggested_fields_json)
    entry_result = await catalog_service.create_catalog_entry(
        state,
        content_type=fields.get("content_type", "file"),
        slug=fields.get("slug", "untitled"),
        title=fields.get("title", suggestion.source_file_id),
        actor=actor,
    )
    entry = entry_result.entry
    release = entry_result.release
    asset_result = await catalog_service.create_catalog_asset(
        state,
        release_id=release.release_id,
        slug=fields.get("asset_slug", fields.get("slug", "asset")),
        display_name=fields.get("asset_display_name", fields.get("title", suggestion.source_file_id)),
        platform=fields.get("platform", ""),
        architecture=fields.get("architecture", "unknown"),
        package_type=fields.get("package_type", "unknown"),
        language=fields.get("language", "unknown"),
        actor=actor,
    )
    asset = asset_result.asset
    try:
        await catalog_service.attach_catalog_location(
            state,
            index,
            asset_id=asset.asset_id,
            resource_id=suggestion.source_file_id,
            actor=actor,
        )
    except catalog_service.CatalogError:
        pass
    suggestion.target_entry_id = entry.entry_id
    suggestion.target_release_id = release.release_id
    suggestion.target_asset_id = asset.asset_id
    suggestion.applied_revision_id = await _latest_revision_id(state, "entry", entry.entry_id)
    return ApplyResult(
        suggestion_id=suggestion.suggestion_id,
        success=True,
        entry_id=entry.entry_id,
        release_id=release.release_id,
        asset_id=asset.asset_id,
    )


async def _apply_new_release(
    state: AsyncSession, suggestion: CatalogSuggestion, actor: str
) -> ApplyResult:
    fields = _decode_json(suggestion.suggested_fields_json)
    entry_id = suggestion.target_entry_id or fields.get("entry_id")
    if not entry_id:
        raise SuggestionStateInvalid(suggestion.suggestion_id, "缺少 target_entry_id")
    release_result = await catalog_service.create_catalog_release(
        state,
        entry_id=entry_id,
        slug=fields.get("slug", "unversioned"),
        title=fields.get("title", "release"),
        channel=fields.get("channel", "unknown"),
        actor=actor,
    )
    release = release_result.release
    suggestion.target_release_id = release.release_id
    suggestion.applied_revision_id = await _latest_revision_id(state, "release", release.release_id)
    return ApplyResult(
        suggestion_id=suggestion.suggestion_id,
        success=True,
        entry_id=entry_id,
        release_id=release.release_id,
    )


async def _apply_asset(
    state: AsyncSession, suggestion: CatalogSuggestion, actor: str
) -> ApplyResult:
    fields = _decode_json(suggestion.suggested_fields_json)
    release_id = suggestion.target_release_id or fields.get("release_id")
    if not release_id:
        raise SuggestionStateInvalid(suggestion.suggestion_id, "缺少 target_release_id")
    asset_result = await catalog_service.create_catalog_asset(
        state,
        release_id=release_id,
        slug=fields.get("slug", "asset"),
        display_name=fields.get("display_name", suggestion.source_file_id),
        platform=fields.get("platform", ""),
        architecture=fields.get("architecture", "unknown"),
        package_type=fields.get("package_type", "unknown"),
        language=fields.get("language", "unknown"),
        actor=actor,
    )
    asset = asset_result.asset
    suggestion.target_asset_id = asset.asset_id
    suggestion.applied_revision_id = await _latest_revision_id(state, "asset", asset.asset_id)
    return ApplyResult(
        suggestion_id=suggestion.suggestion_id,
        success=True,
        release_id=release_id,
        asset_id=asset.asset_id,
    )


async def apply_suggestion(
    state: AsyncSession,
    index: AsyncSession,
    suggestion_id: str,
    *,
    actor: str = "admin",
) -> ApplyResult:
    """事务化 apply 单条建议。幂等：已 applied 直接返回。"""
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
        raise SuggestionStateInvalid(suggestion_id, "已拒绝的建议不能 apply")

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
        raise SuggestionStateInvalid(suggestion_id, f"未知建议类型: {kind}")

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
    """拒绝单条建议。幂等：已 rejected 直接返回。"""
    suggestion = await get_suggestion(state, suggestion_id)
    if suggestion.status == "rejected":
        return suggestion
    if suggestion.status == "applied":
        raise SuggestionStateInvalid(suggestion_id, "已应用的建议不能拒绝，请先撤销")
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
    """批量 apply：逐项独立执行，单项失败不阻塞其他项，不伪装全批成功。"""
    result = BatchApplyResult()
    for sid in suggestion_ids:
        try:
            single = await apply_suggestion(state, index, sid, actor=actor)
            result.results.append(single)
            result.succeeded += 1
        except Exception as exc:
            result.results.append(ApplyResult(suggestion_id=sid, success=False, error=str(exc)))
            result.failed += 1
    return result


async def batch_reject_suggestions(
    state: AsyncSession,
    suggestion_ids: list[str],
    *,
    actor: str = "admin",
    reason: str = "",
) -> BatchApplyResult:
    """批量拒绝：逐项独立执行，单项失败不阻塞其他项。"""
    result = BatchApplyResult()
    for sid in suggestion_ids:
        try:
            await reject_suggestion(state, sid, actor=actor, reason=reason)
            result.results.append(ApplyResult(suggestion_id=sid, success=True))
            result.succeeded += 1
        except Exception as exc:
            result.results.append(ApplyResult(suggestion_id=sid, success=False, error=str(exc)))
            result.failed += 1
    return result


async def revert_suggestion(
    state: AsyncSession,
    suggestion_id: str,
    *,
    actor: str = "admin",
) -> CatalogSuggestion:
    """撤销已应用的建议：产生新修订，不删除底层文件，不破坏既有身份。

    - new_entry: 将 entry 归档（status=archived）
    - new_release: 将 release 归档（status=archived）
    - asset: 将 asset 停用（status=disabled）
    - candidate_duplicate/conflict: 仅恢复建议状态为 reviewed
    撤销后建议状态回到 reviewed，可重新 apply 或 reject。
    """
    suggestion = await get_suggestion(state, suggestion_id)
    if suggestion.status != "applied":
        raise SuggestionStateInvalid(suggestion_id, "仅已应用的建议可撤销")

    kind = suggestion.suggestion_kind
    if kind == _KIND_NEW_ENTRY and suggestion.target_entry_id:
        await catalog_service.update_catalog_entry(
            state,
            suggestion.target_entry_id,
            expected_revision=(
                await catalog_service.get_catalog_entry(state, suggestion.target_entry_id)
            ).revision,
            status="archived",
            actor=actor,
        )
    elif kind == _KIND_NEW_RELEASE and suggestion.target_release_id:
        await catalog_service.update_catalog_release(
            state,
            suggestion.target_release_id,
            status="archived",
            actor=actor,
        )
    elif kind == _KIND_ASSET and suggestion.target_asset_id:
        await catalog_service.update_catalog_asset(
            state,
            suggestion.target_asset_id,
            status="disabled",
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
) -> tuple[list[CatalogRevision], int]:
    """查询与建议关联的内容修订记录（撤销记录查询）。"""
    suggestion = await get_suggestion(state, suggestion_id)
    target_ids: list[tuple[str, str]] = []
    if suggestion.target_entry_id:
        target_ids.append(("entry", suggestion.target_entry_id))
    if suggestion.target_release_id:
        target_ids.append(("release", suggestion.target_release_id))
    if suggestion.target_asset_id:
        target_ids.append(("asset", suggestion.target_asset_id))
    if not target_ids:
        return [], 0
    conditions = []
    for t_type, t_id in target_ids:
        conditions.append(
            (CatalogRevision.target_type == t_type) & (CatalogRevision.target_id == t_id)
        )
    from sqlalchemy import or_
    stmt = select(CatalogRevision).where(or_(*conditions)).order_by(
        CatalogRevision.created_at, CatalogRevision.revision_id
    )
    count_stmt = select(func.count()).select_from(CatalogRevision).where(or_(*conditions))
    stmt = stmt.limit(max(int(limit), 0)).offset(max(int(offset), 0))
    rows = list((await state.scalars(stmt)).all())
    total = int(await state.scalar(count_stmt) or 0)
    return rows, total
