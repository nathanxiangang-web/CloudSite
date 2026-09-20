"""Generate advisory Catalog suggestions from indexed Resources.

This service owns only Automation suggestion state. Resource input comes through
Resources contracts and Catalog classification context comes through Catalog
contracts; no cross-module ORM is imported here.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...catalog.contracts.public import (
    catalog_automation_context,
    find_catalog_duplicate_asset,
)
from ...resources.contracts.public import ParserResourceView, resource_queries
from ..domain.resource_name_parser import (
    PARSER_VERSION,
    UNKNOWN,
    ParseResult,
    parse_resource_name,
)
from ..infrastructure.models import CatalogSuggestion

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
    payload = "\x1f".join(
        [name or "", path or "", extension or "", mime_type or "", str(int(size or 0))]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _evidence_to_dict(parse_result: ParseResult) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, ev in parse_result.evidence.items():
        out[key] = {"token": ev.token, "source": ev.source, "index": ev.index}
    return out


def _json(value: dict[str, Any] | None) -> str:
    return json.dumps(
        value or {},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _confidence_for(parse_result: ParseResult) -> float:
    fields = (
        parse_result.platform,
        parse_result.architecture,
        parse_result.language,
        parse_result.version,
        parse_result.package_form,
    )
    recognized = sum(1 for value in fields if value and value != UNKNOWN)
    return min(0.3 + recognized * 0.1, 0.8)


def _slugify(value: str) -> str:
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
    created: list[CatalogSuggestion] = field(default_factory=list)
    skipped: int = 0


async def _classify_suggestion(
    state: AsyncSession,
    resource: ParserResourceView,
    parse_result: ParseResult,
) -> tuple[str, str | None, str | None, str | None, dict[str, Any], float]:
    context = await catalog_automation_context(state, resource_id=resource.id)

    if context.location_id is None and context.entry_id is None:
        duplicate = await find_catalog_duplicate_asset(
            state,
            display_name=resource.name,
            exclude_resource_id=resource.id,
        )
        if duplicate is not None:
            suggested = {
                "existing_entry_id": duplicate.entry_id,
                "existing_entry_slug": duplicate.entry_slug,
                "existing_asset_id": duplicate.asset_id,
                "existing_asset_display_name": duplicate.asset_display_name,
                "reason": "同名资源已存在于其他条目",
            }
            return (
                _KIND_CANDIDATE_DUPLICATE,
                duplicate.entry_id,
                None,
                duplicate.asset_id,
                suggested,
                0.5,
            )

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
        return (
            _KIND_NEW_ENTRY,
            None,
            None,
            None,
            suggested,
            _confidence_for(parse_result),
        )

    if (
        context.entry_id is not None
        and context.release_id is not None
        and context.asset_id is not None
    ):
        conflicts: list[dict[str, Any]] = []
        if (
            parse_result.platform != UNKNOWN
            and context.asset_platform
            and parse_result.platform != context.asset_platform
        ):
            conflicts.append(
                {
                    "field": "platform",
                    "parsed": parse_result.platform,
                    "existing": context.asset_platform,
                }
            )
        if (
            parse_result.architecture != UNKNOWN
            and context.asset_architecture != "unknown"
            and parse_result.architecture != context.asset_architecture
        ):
            conflicts.append(
                {
                    "field": "architecture",
                    "parsed": parse_result.architecture,
                    "existing": context.asset_architecture,
                }
            )
        if (
            parse_result.package_form != UNKNOWN
            and context.asset_package_type != "unknown"
            and parse_result.package_form != context.asset_package_type
        ):
            conflicts.append(
                {
                    "field": "package_type",
                    "parsed": parse_result.package_form,
                    "existing": context.asset_package_type,
                }
            )
        if conflicts:
            return (
                _KIND_CONFLICT,
                context.entry_id,
                context.release_id,
                context.asset_id,
                {
                    "conflicts": conflicts,
                    "entry_id": context.entry_id,
                    "asset_id": context.asset_id,
                },
                0.4,
            )

        if parse_result.version != UNKNOWN and context.release_slug == "unversioned":
            return (
                _KIND_NEW_RELEASE,
                context.entry_id,
                None,
                None,
                {
                    "entry_id": context.entry_id,
                    "slug": _slugify(parse_result.version),
                    "title": parse_result.version,
                    "channel": "stable",
                    "version": parse_result.version,
                },
                _confidence_for(parse_result),
            )

        if parse_result.platform != UNKNOWN and not context.asset_platform:
            return (
                _KIND_ASSET,
                context.entry_id,
                context.release_id,
                None,
                {
                    "release_id": context.release_id,
                    "slug": _slugify(
                        f"{parse_result.platform}-{parse_result.architecture}"
                    ),
                    "display_name": resource.name,
                    "platform": parse_result.platform,
                    "architecture": parse_result.architecture,
                    "package_type": parse_result.package_form,
                    "language": parse_result.language,
                },
                _confidence_for(parse_result),
            )

    return (
        _KIND_NEW_ENTRY,
        None,
        None,
        None,
        {
            "content_type": resource.content_type,
            "slug": _slugify(resource.name),
            "title": resource.name,
        },
        _confidence_for(parse_result),
    )


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
    resource: ParserResourceView,
) -> GenerationResult:
    """Generate one advisory suggestion without mutating formal Catalog state."""

    del index  # retained for legacy signature compatibility
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

    (
        kind,
        target_entry_id,
        target_release_id,
        target_asset_id,
        suggested_fields,
        confidence,
    ) = await _classify_suggestion(state, resource, parse_result)

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
    """Generate suggestions for a bounded list of active Resource views."""

    result = GenerationResult()
    resources = await resource_queries(index).list_parser_resources(
        content_type=content_type,
        limit=max(int(limit), 0),
    )
    for resource in resources:
        single = await generate_suggestions_for_resource(state, index, resource)
        result.created.extend(single.created)
        result.skipped += single.skipped
    return result
