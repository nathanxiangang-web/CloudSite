"""Catalog public facade used by Automation suggestion workflows.

Automation must not import Catalog ORM or legacy services. This facade keeps
classification reads, approved suggestion writes, revert commands, and revision
reads inside Catalog ownership and exposes persistence-neutral result objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure.models import (
    CatalogAsset,
    CatalogEntry,
    CatalogLocation,
    CatalogRelease,
    CatalogRevision,
)
from .catalog_entry import (
    CatalogError,
    create_catalog_entry,
    get_catalog_entry,
    update_catalog_entry,
)
from .catalog_release import (
    attach_catalog_location,
    create_catalog_asset,
    create_catalog_release,
    update_catalog_asset,
    update_catalog_release,
)


@dataclass(frozen=True, slots=True)
class CatalogAutomationContext:
    location_id: str | None = None
    entry_id: str | None = None
    entry_slug: str | None = None
    release_id: str | None = None
    release_slug: str | None = None
    asset_id: str | None = None
    asset_display_name: str | None = None
    asset_platform: str = ""
    asset_architecture: str = "unknown"
    asset_package_type: str = "unknown"


@dataclass(frozen=True, slots=True)
class CatalogDuplicateView:
    entry_id: str
    entry_slug: str
    asset_id: str
    asset_display_name: str


@dataclass(frozen=True, slots=True)
class CatalogAutomationApplyResult:
    entry_id: str | None = None
    release_id: str | None = None
    asset_id: str | None = None
    revision_id: str | None = None


@dataclass(frozen=True, slots=True)
class CatalogRevisionView:
    revision_id: str
    target_type: str
    target_id: str
    action: str
    actor: str
    source: str
    base_revision: int | None
    resulting_revision: int | None
    summary: str
    before_json: str
    after_json: str
    diff_json: str
    payload_json: str
    created_at: datetime


async def catalog_automation_context(
    state: AsyncSession,
    *,
    resource_id: str,
) -> CatalogAutomationContext:
    location = await state.scalar(
        select(CatalogLocation)
        .where(CatalogLocation.resource_id == resource_id)
        .limit(1)
    )
    if location is None:
        return CatalogAutomationContext()

    asset = await state.get(CatalogAsset, location.asset_id)
    if asset is None:
        return CatalogAutomationContext(location_id=location.location_id)

    release = await state.get(CatalogRelease, asset.release_id)
    if release is None:
        return CatalogAutomationContext(
            location_id=location.location_id,
            asset_id=asset.asset_id,
            asset_display_name=asset.display_name,
            asset_platform=asset.platform,
            asset_architecture=asset.architecture,
            asset_package_type=asset.package_type,
        )

    entry = await state.get(CatalogEntry, release.entry_id)
    return CatalogAutomationContext(
        location_id=location.location_id,
        entry_id=entry.entry_id if entry is not None else None,
        entry_slug=entry.slug if entry is not None else None,
        release_id=release.release_id,
        release_slug=release.slug,
        asset_id=asset.asset_id,
        asset_display_name=asset.display_name,
        asset_platform=asset.platform,
        asset_architecture=asset.architecture,
        asset_package_type=asset.package_type,
    )


async def find_catalog_duplicate_asset(
    state: AsyncSession,
    *,
    display_name: str,
    exclude_resource_id: str,
) -> CatalogDuplicateView | None:
    locations = list(
        (
            await state.scalars(
                select(CatalogLocation).where(
                    CatalogLocation.resource_id != exclude_resource_id
                )
            )
        ).all()
    )
    for location in locations:
        asset = await state.get(CatalogAsset, location.asset_id)
        if asset is None or asset.display_name != display_name:
            continue
        release = await state.get(CatalogRelease, asset.release_id)
        if release is None:
            continue
        entry = await state.get(CatalogEntry, release.entry_id)
        if entry is None:
            continue
        return CatalogDuplicateView(
            entry_id=entry.entry_id,
            entry_slug=entry.slug,
            asset_id=asset.asset_id,
            asset_display_name=asset.display_name,
        )
    return None


async def _latest_revision_id(
    state: AsyncSession,
    *,
    target_type: str,
    target_id: str,
) -> str | None:
    row = await state.scalar(
        select(CatalogRevision)
        .where(
            CatalogRevision.target_type == target_type,
            CatalogRevision.target_id == target_id,
        )
        .order_by(CatalogRevision.created_at.desc(), CatalogRevision.revision_id.desc())
        .limit(1)
    )
    return row.revision_id if row is not None else None


async def apply_automation_new_entry(
    state: AsyncSession,
    index: AsyncSession,
    *,
    source_resource_id: str,
    fields: dict[str, Any],
    actor: str,
) -> CatalogAutomationApplyResult:
    entry_result = await create_catalog_entry(
        state,
        content_type=fields.get("content_type", "file"),
        slug=fields.get("slug", "untitled"),
        title=fields.get("title", source_resource_id),
        actor=actor,
    )
    entry = entry_result.entry
    release = entry_result.release

    asset_result = await create_catalog_asset(
        state,
        release_id=release.release_id,
        slug=fields.get("asset_slug", fields.get("slug", "asset")),
        display_name=fields.get(
            "asset_display_name", fields.get("title", source_resource_id)
        ),
        platform=fields.get("platform", ""),
        architecture=fields.get("architecture", "unknown"),
        package_type=fields.get("package_type", "unknown"),
        language=fields.get("language", "unknown"),
        actor=actor,
    )
    asset = asset_result.asset

    try:
        await attach_catalog_location(
            state,
            index,
            asset_id=asset.asset_id,
            resource_id=source_resource_id,
            actor=actor,
        )
    except CatalogError:
        # Preserve legacy suggestion behavior: content can still be created when
        # a location is stale/unavailable; the editor can repair the binding.
        pass

    return CatalogAutomationApplyResult(
        entry_id=entry.entry_id,
        release_id=release.release_id,
        asset_id=asset.asset_id,
        revision_id=await _latest_revision_id(
            state, target_type="entry", target_id=entry.entry_id
        ),
    )


async def apply_automation_new_release(
    state: AsyncSession,
    *,
    entry_id: str,
    fields: dict[str, Any],
    actor: str,
) -> CatalogAutomationApplyResult:
    result = await create_catalog_release(
        state,
        entry_id=entry_id,
        slug=fields.get("slug", "unversioned"),
        title=fields.get("title", "release"),
        channel=fields.get("channel", "unknown"),
        actor=actor,
    )
    release = result.release
    return CatalogAutomationApplyResult(
        entry_id=entry_id,
        release_id=release.release_id,
        revision_id=await _latest_revision_id(
            state, target_type="release", target_id=release.release_id
        ),
    )


async def apply_automation_asset(
    state: AsyncSession,
    *,
    release_id: str,
    source_resource_id: str,
    fields: dict[str, Any],
    actor: str,
) -> CatalogAutomationApplyResult:
    result = await create_catalog_asset(
        state,
        release_id=release_id,
        slug=fields.get("slug", "asset"),
        display_name=fields.get("display_name", source_resource_id),
        platform=fields.get("platform", ""),
        architecture=fields.get("architecture", "unknown"),
        package_type=fields.get("package_type", "unknown"),
        language=fields.get("language", "unknown"),
        actor=actor,
    )
    asset = result.asset
    return CatalogAutomationApplyResult(
        release_id=release_id,
        asset_id=asset.asset_id,
        revision_id=await _latest_revision_id(
            state, target_type="asset", target_id=asset.asset_id
        ),
    )


async def revert_automation_target(
    state: AsyncSession,
    *,
    target_type: str,
    target_id: str,
    actor: str,
) -> None:
    if target_type == "entry":
        entry = await get_catalog_entry(state, target_id)
        await update_catalog_entry(
            state,
            target_id,
            expected_revision=entry.revision,
            status="archived",
            actor=actor,
        )
        return
    if target_type == "release":
        await update_catalog_release(
            state,
            target_id,
            status="archived",
            actor=actor,
        )
        return
    if target_type == "asset":
        await update_catalog_asset(
            state,
            target_id,
            status="disabled",
            actor=actor,
        )
        return
    raise ValueError(f"unsupported automation target type: {target_type}")


def _revision_view(row: CatalogRevision) -> CatalogRevisionView:
    return CatalogRevisionView(
        revision_id=row.revision_id,
        target_type=row.target_type,
        target_id=row.target_id,
        action=row.action,
        actor=row.actor,
        source=row.source,
        base_revision=row.base_revision,
        resulting_revision=row.resulting_revision,
        summary=row.summary,
        before_json=row.before_json,
        after_json=row.after_json,
        diff_json=row.diff_json,
        payload_json=row.payload_json,
        created_at=row.created_at,
    )


async def list_automation_revisions(
    state: AsyncSession,
    *,
    targets: list[tuple[str, str]],
    limit: int,
    offset: int,
) -> tuple[list[CatalogRevisionView], int]:
    if not targets:
        return [], 0
    conditions = [
        (CatalogRevision.target_type == target_type)
        & (CatalogRevision.target_id == target_id)
        for target_type, target_id in targets
    ]
    predicate = or_(*conditions)
    stmt = (
        select(CatalogRevision)
        .where(predicate)
        .order_by(CatalogRevision.created_at, CatalogRevision.revision_id)
        .limit(max(int(limit), 0))
        .offset(max(int(offset), 0))
    )
    count_stmt = (
        select(func.count())
        .select_from(CatalogRevision)
        .where(predicate)
    )
    rows = list((await state.scalars(stmt)).all())
    total = int(await state.scalar(count_stmt) or 0)
    return [_revision_view(row) for row in rows], total


__all__ = [
    "CatalogAutomationContext",
    "CatalogDuplicateView",
    "CatalogAutomationApplyResult",
    "CatalogRevisionView",
    "catalog_automation_context",
    "find_catalog_duplicate_asset",
    "apply_automation_new_entry",
    "apply_automation_new_release",
    "apply_automation_asset",
    "revert_automation_target",
    "list_automation_revisions",
]
