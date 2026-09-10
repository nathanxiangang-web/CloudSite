"""A2 候选生成接入：影子模式调用 A1 resource_name_parser 生成整理建议。

本服务只生成 catalog_suggestions 草稿，绝不修改正式 catalog 内容
（entries/releases/assets/locations）。apply 动作由 suggestion_review 服务
在管理员确认后执行。生成幂等：相同 (source_file_id, file_fingerprint,
parser_version, suggestion_kind) 已存在则跳过，既不重复生成草稿，也不
覆盖人工已确认的结果。文件变化（指纹不同）或规则升级（解析器版本不同）
会产生新草稿，旧的人工确认结果保留。
"""
from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    CatalogAsset,
    CatalogEntry,
    CatalogLocation,
    CatalogRelease,
    CatalogSuggestion,
    Resource,
)
from .resource_name_parser import UNKNOWN, PARSER_VERSION, ParseResult, parse_resource_name

SUGGESTION_ID_PREFIX = "cs_"
_ID_HEX_LEN = 32

_KIND_NEW_ENTRY = "new_entry"
_KIND_NEW_RELEASE = "new_release"
_KIND_ASSET = "asset"
_KIND_CANDIDATE_DUPLICATE = "candidate_duplicate"
_KIND_CONFLICT = "conflict"
ALL_KINDS = (
    _KIND_NEW_ENTRY,
    _KIND_NEW_RELEASE,
    _KIND_ASSET,
    _KIND_CANDIDATE_DUPLICATE,
    _KIND_CONFLICT,
)


def _new_id(prefix: str) -> str:
    return prefix + secrets.token_hex(_ID_HEX_LEN // 2)


def compute_file_fingerprint(
    *,
    name: str,
    path: str,
    extension: str,
    mime_type: str,
    size: int,
) -> str:
    """基于文件稳定属性计算 SHA-256 指纹。

    指纹随文件名、路径、扩展名、MIME 类型或大小变化而变化；文件变化产生
    新指纹，进而产生新草稿，旧的人工确认结果保留。
    """
    payload = "\x1f".join(
        [name or "", path or "", extension or "", mime_type or "", str(int(size or 0))]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _evidence_to_dict(parse_result: ParseResult) -> dict[str, Any]:
    """将 ParseResult.evidence 序列化为可 JSON 存储的 dict。"""
    out: dict[str, Any] = {}
    for key, ev in parse_result.evidence.items():
        out[key] = {"token": ev.token, "source": ev.source, "index": ev.index}
    return out


def _json(value: dict[str, Any] | None) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _confidence_for(parse_result: ParseResult) -> float:
    """根据识别出的字段数量计算置信度。base 0.3，每识别一个非 unknown 字段 +0.1，上限 0.8。"""
    base = 0.3
    fields = (
        parse_result.platform,
        parse_result.architecture,
        parse_result.language,
        parse_result.version,
        parse_result.package_form,
    )
    recognized = sum(1 for value in fields if value and value != UNKNOWN)
    return min(base + recognized * 0.1, 0.8)


def _slugify(value: str) -> str:
    """保守 slug 生成：小写、非字母数字替换为连字符、去首尾连字符。"""
    cleaned = []
    for char in value.lower():
        if char.isalnum():
            cleaned.append(char)
        elif char in "-_.":
            cleaned.append("-")
        else:
            cleaned.append("-")
    slug = "".join(cleaned)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "untitled"


@dataclass
class GenerationResult:
    """单次生成的结果：新建的建议行与跳过计数。"""
    created: list[CatalogSuggestion] = field(default_factory=list)
    skipped: int = 0


async def _existing_location_for_resource(
    state: AsyncSession, resource_id: str
) -> tuple[CatalogLocation | None, CatalogAsset | None, CatalogRelease | None, CatalogEntry | None]:
    """查询资源是否已绑定到 catalog location，返回四级关联或 None。"""
    location = await state.scalar(
        select(CatalogLocation).where(CatalogLocation.resource_id == resource_id)
    )
    if location is None:
        return None, None, None, None
    asset = await state.get(CatalogAsset, location.asset_id)
    if asset is None:
        return location, None, None, None
    release = await state.get(CatalogRelease, asset.release_id)
    if release is None:
        return location, asset, None, None
    entry = await state.get(CatalogEntry, release.entry_id)
    return location, asset, release, entry


async def _duplicate_candidate(
    state: AsyncSession, resource: Resource, exclude_resource_id: str
) -> tuple[CatalogEntry | None, CatalogAsset | None]:
    """查找同名资源是否已绑定到其他 catalog asset（候选重复）。"""
    same_name_locations = list(
        (
            await state.scalars(
                select(CatalogLocation).where(
                    CatalogLocation.resource_id != exclude_resource_id,
                )
            )
        ).all()
    )
    for loc in same_name_locations:
        asset = await state.get(CatalogAsset, loc.asset_id)
        if asset is None:
            continue
        release = await state.get(CatalogRelease, asset.release_id)
        if release is None:
            continue
        entry = await state.get(CatalogEntry, release.entry_id)
        if entry is None:
            continue
        if asset.display_name == resource.name:
            return entry, asset
    return None, None


async def _classify_suggestion(
    state: AsyncSession,
    resource: Resource,
    parse_result: ParseResult,
) -> tuple[str, str | None, str | None, str | None, dict[str, Any], float]:
    """判断建议类型并构造建议字段。

    返回 (kind, target_entry_id, target_release_id, target_asset_id,
    suggested_fields, confidence)。
    """
    location, asset, release, entry = await _existing_location_for_resource(
        state, resource.id
    )

    if location is None and entry is None:
        dup_entry, dup_asset = await _duplicate_candidate(state, resource, resource.id)
        if dup_entry is not None and dup_asset is not None:
            suggested = {
                "existing_entry_id": dup_entry.entry_id,
                "existing_entry_slug": dup_entry.slug,
                "existing_asset_id": dup_asset.asset_id,
                "existing_asset_display_name": dup_asset.display_name,
                "reason": "同名资源已存在于其他条目",
            }
            return _KIND_CANDIDATE_DUPLICATE, dup_entry.entry_id, None, dup_asset.asset_id, suggested, 0.5

        suggested = {
            "content_type": resource.content_type,
            "slug": _slugify(resource.name),
            "title": resource.name,
            "release_slug": "unversioned",
            "release_title": "Default",
            "asset_slug": _slugify(resource.name),
            "asset_display_name": resource.name,
            "platform": parse_result.platform,
            "architecture": parse_result.architecture,
            "package_type": parse_result.package_form,
            "language": parse_result.language,
            "version": parse_result.version,
        }
        return _KIND_NEW_ENTRY, None, None, None, suggested, _confidence_for(parse_result)

    if entry is not None and release is not None and asset is not None:
        conflicts: list[dict[str, Any]] = []
        if parse_result.platform != UNKNOWN and asset.platform and parse_result.platform != asset.platform:
            conflicts.append({"field": "platform", "parsed": parse_result.platform, "existing": asset.platform})
        if parse_result.architecture != UNKNOWN and asset.architecture != "unknown" and parse_result.architecture != asset.architecture:
            conflicts.append({"field": "architecture", "parsed": parse_result.architecture, "existing": asset.architecture})
        if parse_result.package_form != UNKNOWN and asset.package_type != "unknown" and parse_result.package_form != asset.package_type:
            conflicts.append({"field": "package_type", "parsed": parse_result.package_form, "existing": asset.package_type})
        if conflicts:
            suggested = {"conflicts": conflicts, "entry_id": entry.entry_id, "asset_id": asset.asset_id}
            return _KIND_CONFLICT, entry.entry_id, release.release_id, asset.asset_id, suggested, 0.4

        if parse_result.version != UNKNOWN and release.slug == "unversioned":
            suggested = {
                "entry_id": entry.entry_id,
                "slug": _slugify(parse_result.version),
                "title": parse_result.version,
                "channel": "stable",
                "version": parse_result.version,
            }
            return _KIND_NEW_RELEASE, entry.entry_id, None, None, suggested, _confidence_for(parse_result)

        if parse_result.platform != UNKNOWN and (not asset.platform or asset.platform == ""):
            suggested = {
                "release_id": release.release_id,
                "slug": _slugify(f"{parse_result.platform}-{parse_result.architecture}"),
                "display_name": resource.name,
                "platform": parse_result.platform,
                "architecture": parse_result.architecture,
                "package_type": parse_result.package_form,
                "language": parse_result.language,
            }
            return _KIND_ASSET, entry.entry_id, release.release_id, None, suggested, _confidence_for(parse_result)

    return _KIND_NEW_ENTRY, None, None, None, {
        "content_type": resource.content_type,
        "slug": _slugify(resource.name),
        "title": resource.name,
    }, _confidence_for(parse_result)


async def _insert_if_absent(
    state: AsyncSession,
    *,
    source_file_id: str,
    file_fingerprint: str,
    parser_version: str,
    suggestion_kind: str,
    target_entry_id: str | None,
    target_release_id: str | None,
    target_asset_id: str | None,
    suggested_fields: dict[str, Any],
    evidence: dict[str, Any],
    confidence: float,
) -> CatalogSuggestion | None:
    """幂等插入：相同指纹+解析器版本+类型已存在则返回 None（跳过）。

    不覆盖人工已确认的结果：已存在的行无论状态如何都不更新。
    """
    existing = await state.scalar(
        select(CatalogSuggestion).where(
            CatalogSuggestion.source_file_id == source_file_id,
            CatalogSuggestion.file_fingerprint == file_fingerprint,
            CatalogSuggestion.parser_version == parser_version,
            CatalogSuggestion.suggestion_kind == suggestion_kind,
        )
    )
    if existing is not None:
        return None
    row = CatalogSuggestion(
        suggestion_id=_new_id(SUGGESTION_ID_PREFIX),
        source_file_id=source_file_id,
        file_fingerprint=file_fingerprint,
        parser_version=parser_version,
        suggestion_kind=suggestion_kind,
        target_entry_id=target_entry_id,
        target_release_id=target_release_id,
        target_asset_id=target_asset_id,
        suggested_fields_json=_json(suggested_fields),
        evidence_json=_json(evidence),
        confidence=confidence,
        status="pending",
    )
    state.add(row)
    await state.flush()
    return row


async def generate_suggestions_for_resource(
    state: AsyncSession,
    index: AsyncSession,
    resource: Resource,
) -> GenerationResult:
    """为单个 index 资源生成整理建议（影子模式，不改正式内容）。

    调用 A1 parse_resource_name 解析资源名，根据现有 catalog 状态分类建议
    类型，幂等写入 catalog_suggestions。事务由调用方持有并 commit。
    """
    result = GenerationResult()
    parse_result = parse_resource_name(
        resource.id,
        resource.name,
        resource.path,
        resource.extension,
        resource.mime_type,
    )
    fingerprint = compute_file_fingerprint(
        name=resource.name,
        path=resource.path,
        extension=resource.extension,
        mime_type=resource.mime_type,
        size=resource.size,
    )
    evidence = _evidence_to_dict(parse_result)
    evidence["parser_version"] = parse_result.parser_version
    evidence["original_name"] = parse_result.original_name

    kind, target_entry_id, target_release_id, target_asset_id, suggested_fields, confidence = (
        await _classify_suggestion(state, resource, parse_result)
    )

    row = await _insert_if_absent(
        state,
        source_file_id=resource.id,
        file_fingerprint=fingerprint,
        parser_version=parse_result.parser_version,
        suggestion_kind=kind,
        target_entry_id=target_entry_id,
        target_release_id=target_release_id,
        target_asset_id=target_asset_id,
        suggested_fields=suggested_fields,
        evidence=evidence,
        confidence=confidence,
    )
    if row is not None:
        result.created.append(row)
    else:
        result.skipped += 1
    return result


async def generate_suggestions_batch(
    state: AsyncSession,
    index: AsyncSession,
    *,
    limit: int = 200,
    content_type: str | None = None,
) -> GenerationResult:
    """批量扫描 index 资源并生成建议（影子模式）。

    按 indexed_at 升序扫描 active 资源，对每个资源调用
    generate_suggestions_for_resource。limit 控制单批扫描上限以避免长事务。
    """
    result = GenerationResult()
    stmt = (
        select(Resource)
        .where(Resource.status == "active")
        .order_by(Resource.indexed_at)
        .limit(max(int(limit), 0))
    )
    if content_type is not None:
        stmt = stmt.where(Resource.content_type == content_type)
    resources = list((await index.scalars(stmt)).all())
    for resource in resources:
        single = await generate_suggestions_for_resource(state, index, resource)
        result.created.extend(single.created)
        result.skipped += single.skipped
    return result
