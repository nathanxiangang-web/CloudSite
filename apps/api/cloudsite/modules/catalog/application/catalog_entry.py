"""Catalog entry application services: create, edit, preview, publish.

Split from services/catalog.py (C2). Pure application services over the
CatalogEntry state model and the 1.0.0 Resource index. Release/asset/location
operations live in catalog_release.py; shared exceptions and helpers defined
here are re-exported by that module.

No FastAPI or HTTPException is imported here; routers translate the domain
exceptions into HTTP responses at the boundary. Transaction ownership stays
with the caller; every function only flushes within the supplied sessions.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...providers.contracts.public import enabled_root_ids
from ...resources.contracts.public import CatalogResourceView, resource_queries
from ..infrastructure.models import (
    CatalogAsset,
    CatalogEntry,
    CatalogLocation,
    CatalogRelease,
    utcnow,
)
from .outbox import enqueue_catalog_search_outbox
from .revisions import append_catalog_revision

ENTRY_ID_PREFIX = "ce_"
RELEASE_ID_PREFIX = "cr_"
ASSET_ID_PREFIX = "ca_"
LOCATION_ID_PREFIX = "cl_"
_ID_HEX_LEN = 32
DEFAULT_RELEASE_SLUG = "unversioned"
DEFAULT_RELEASE_TITLE = "Default"

_UNSET: object = object()


def _new_id(prefix: str) -> str:
    return prefix + secrets.token_hex(_ID_HEX_LEN // 2)


def _entry_snapshot(entry: CatalogEntry) -> dict:
    return {
        "content_type": entry.content_type,
        "slug": entry.slug,
        "title": entry.title,
        "summary": entry.summary,
        "description": entry.description,
        "cover_resource_id": entry.cover_resource_id,
        "status": entry.status,
        "revision": entry.revision,
        "sort_order": entry.sort_order,
    }
class CatalogError(Exception):
    """Base class for catalog application-layer errors."""


class CatalogEntryNotFound(CatalogError):
    def __init__(self, entry_id: str):
        super().__init__(f"catalog entry not found: {entry_id}")
        self.entry_id = entry_id
class CatalogRevisionConflict(CatalogError):
    def __init__(self, entry_id: str, expected: int, actual: int):
        super().__init__(
            f"revision conflict for {entry_id}: expected {expected}, actual {actual}"
        )
        self.entry_id = entry_id
        self.expected = expected
        self.actual = actual


class CatalogSlugConflict(CatalogError):
    def __init__(self, slug: str):
        super().__init__(f"catalog slug already exists: {slug}")
        self.slug = slug
class CatalogPublishValidationFailed(CatalogError):
    def __init__(self, entry_id: str, reasons: list[str]):
        super().__init__(f"publish validation failed for {entry_id}")
        self.entry_id = entry_id
        self.reasons = reasons
class CatalogAssetNotDownloadable(CatalogError):
    def __init__(self, asset_id: str, reason: str):
        super().__init__(f"catalog asset not downloadable: {asset_id} ({reason})")
        self.asset_id = asset_id
        self.reason = reason
@dataclass
class CreateCatalogEntryResult:
    entry: CatalogEntry
    release: CatalogRelease
@dataclass
class LocationResolution:
    resource_id: str
    root_mapping_id: int | None
    available: bool
    reason: str = ""
@dataclass
class PreviewValidationResult:
    entry_id: str
    status: str
    available: bool
    releases: list[dict] = field(default_factory=list)
    unavailable_locations: list[dict] = field(default_factory=list)


@dataclass
class PublishCatalogEntryResult:
    entry: CatalogEntry
    published_at: datetime
def _resolve_location(
    resource: CatalogResourceView | None,
    resource_id: str,
    roots: set[int],
    expected_content_type: str | None = None,
) -> LocationResolution:
    if resource is None:
        return LocationResolution(resource_id, None, False, "missing")
    if resource.status != "active":
        return LocationResolution(
            resource_id, resource.root_mapping_id, False, "inactive"
        )
    if resource.root_mapping_id is None:
        return LocationResolution(resource_id, None, False, "no_root")
    if resource.root_mapping_id not in roots:
        return LocationResolution(
            resource_id, resource.root_mapping_id, False, "disabled_root"
        )
    if (
        expected_content_type is not None
        and resource.content_type != expected_content_type
    ):
        return LocationResolution(
            resource_id, resource.root_mapping_id, False, "content_type_mismatch"
        )
    return LocationResolution(
        resource_id, resource.root_mapping_id, True, ""
    )
async def create_catalog_entry(
    state: AsyncSession,
    *,
    content_type: str,
    slug: str,
    title: str,
    summary: str = "",
    description: str = "",
    cover_resource_id: str | None = None,
    sort_order: int = 0,
    actor: str = "system",
    entry_id: str | None = None,
    release_id: str | None = None,
) -> CreateCatalogEntryResult:
    """Create a draft entry and exactly one default unversioned release.

    Retry-safe: if ``entry_id`` is supplied and an entry with that id already
    exists, the existing entry and its default release are returned without
    writing a duplicate. A slug collision with a different entry id raises
    ``CatalogSlugConflict`` so retries cannot create duplicate entries.
    """
    if entry_id is not None:
        existing = await state.get(CatalogEntry, entry_id)
        if existing is not None:
            release = await state.scalar(
                select(CatalogRelease).where(
                    CatalogRelease.entry_id == existing.entry_id,
                    CatalogRelease.slug == DEFAULT_RELEASE_SLUG,
                )
            )
            if release is not None:
                return CreateCatalogEntryResult(entry=existing, release=release)

    existing_slug = await state.scalar(
        select(CatalogEntry).where(CatalogEntry.slug == slug)
    )
    if existing_slug is not None:
        raise CatalogSlugConflict(slug)

    entry_id = entry_id or _new_id(ENTRY_ID_PREFIX)
    release_id = release_id or _new_id(RELEASE_ID_PREFIX)
    entry = CatalogEntry(
        entry_id=entry_id,
        content_type=content_type,
        slug=slug,
        title=title,
        summary=summary,
        description=description,
        cover_resource_id=cover_resource_id,
        status="draft",
        sort_order=sort_order,
    )
    release = CatalogRelease(
        release_id=release_id,
        entry_id=entry_id,
        slug=DEFAULT_RELEASE_SLUG,
        title=DEFAULT_RELEASE_TITLE,
        status="draft",
    )
    state.add_all([entry, release])
    await state.flush()
    await append_catalog_revision(
        state,
        target_type="entry",
        target_id=entry.entry_id,
        action="create",
        actor=actor,
        resulting_revision=entry.revision,
        after=_entry_snapshot(entry),
    )
    await append_catalog_revision(
        state,
        target_type="release",
        target_id=release.release_id,
        action="create",
        actor=actor,
        after={
            "entry_id": entry.entry_id,
            "slug": release.slug,
            "title": release.title,
            "status": release.status,
        },
    )
    await enqueue_catalog_search_outbox(state, entry_id=entry.entry_id, revision=entry.revision, action="upsert")
    return CreateCatalogEntryResult(entry=entry, release=release)


async def get_catalog_entry(state: AsyncSession, entry_id: str) -> CatalogEntry:
    entry = await state.get(CatalogEntry, entry_id)
    if entry is None:
        raise CatalogEntryNotFound(entry_id)
    return entry


async def list_catalog_entries(
    state: AsyncSession,
    *,
    content_type: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[CatalogEntry]:
    stmt = select(CatalogEntry).order_by(
        CatalogEntry.sort_order, CatalogEntry.created_at
    )
    if content_type is not None:
        stmt = stmt.where(CatalogEntry.content_type == content_type)
    if status is not None:
        stmt = stmt.where(CatalogEntry.status == status)
    stmt = stmt.limit(max(int(limit), 0)).offset(max(int(offset), 0))
    return list((await state.scalars(stmt)).all())


async def update_catalog_entry(
    state: AsyncSession,
    entry_id: str,
    *,
    expected_revision: int,
    slug: str | object = _UNSET,
    title: str | object = _UNSET,
    summary: str | object = _UNSET,
    description: str | object = _UNSET,
    cover_resource_id: str | None | object = _UNSET,
    content_type: str | object = _UNSET,
    sort_order: int | object = _UNSET,
    status: str | object = _UNSET,
    actor: str = "system",
) -> CatalogEntry:
    """Apply an optimistic-revision update to an entry.

    ``expected_revision`` must match the current ``entry.revision``. On success
    the revision is incremented by one in the same session transaction. Fields
    left as the sentinel ``_UNSET`` are not modified; ``cover_resource_id`` may
    be cleared by passing ``None`` explicitly.
    """
    entry = await state.get(CatalogEntry, entry_id)
    if entry is None:
        raise CatalogEntryNotFound(entry_id)
    if entry.revision != expected_revision:
        raise CatalogRevisionConflict(entry_id, expected_revision, entry.revision)

    before = _entry_snapshot(entry)
    changed = False
    if slug is not _UNSET and entry.slug != slug:
        existing_slug = await state.scalar(
            select(CatalogEntry).where(
                CatalogEntry.slug == slug,
                CatalogEntry.entry_id != entry_id,
            )
        )
        if existing_slug is not None:
            raise CatalogSlugConflict(str(slug))
        entry.slug = slug  # type: ignore[assignment]
        changed = True
    if title is not _UNSET and entry.title != title:
        entry.title = title  # type: ignore[assignment]
        changed = True
    if summary is not _UNSET and entry.summary != summary:
        entry.summary = summary  # type: ignore[assignment]
        changed = True
    if description is not _UNSET and entry.description != description:
        entry.description = description  # type: ignore[assignment]
        changed = True
    if cover_resource_id is not _UNSET and entry.cover_resource_id != cover_resource_id:
        entry.cover_resource_id = cover_resource_id  # type: ignore[assignment]
        changed = True
    if content_type is not _UNSET and entry.content_type != content_type:
        entry.content_type = content_type  # type: ignore[assignment]
        changed = True
    if sort_order is not _UNSET and entry.sort_order != sort_order:
        entry.sort_order = sort_order  # type: ignore[assignment]
        changed = True
    if status is not _UNSET and entry.status != status:
        entry.status = status  # type: ignore[assignment]
        changed = True

    if changed:
        entry.revision = entry.revision + 1
        await state.flush()
        after = _entry_snapshot(entry)
        diff = {
            key: [before.get(key), after.get(key)]
            for key in after
            if before.get(key) != after.get(key)
        }
        await append_catalog_revision(
            state,
            target_type="entry",
            target_id=entry.entry_id,
            action="update",
            actor=actor,
            base_revision=expected_revision,
            resulting_revision=entry.revision,
            before=before,
            after=after,
            diff=diff,
        )
    if changed:
        await enqueue_catalog_search_outbox(state, entry_id=entry.entry_id, revision=entry.revision, action="upsert")
    return entry
async def _collect_location_blockers(
    state: AsyncSession,
    index: AsyncSession,
    entry_id: str,
    roots: set[int],
    expected_content_type: str,
) -> list[str]:
    reasons: list[str] = []
    available_count = 0
    releases = list(
        (
            await state.scalars(
                select(CatalogRelease).where(
                    CatalogRelease.entry_id == entry_id
                )
            )
        ).all()
    )
    for release in releases:
        assets = list(
            (
                await state.scalars(
                    select(CatalogAsset).where(
                        CatalogAsset.release_id == release.release_id,
                        CatalogAsset.status == "active",
                    )
                )
            ).all()
        )
        for asset in assets:
            locations = list(
                (
                    await state.scalars(
                        select(CatalogLocation).where(
                            CatalogLocation.asset_id == asset.asset_id,
                            CatalogLocation.status == "active",
                        )
                    )
                ).all()
            )
            for loc in locations:
                resource = await resource_queries(index).catalog_resource(resource_id=loc.resource_id)
                resolution = _resolve_location(
                    resource, loc.resource_id, roots, expected_content_type
                )
                if resolution.available:
                    available_count += 1
                else:
                    reasons.append(
                        f"location {loc.location_id} -> {loc.resource_id}: {resolution.reason}"
                    )
    if available_count == 0:
        reasons.append("entry has no available active catalog location")
    return reasons


async def validate_catalog_entry_for_preview(
    state: AsyncSession,
    index: AsyncSession,
    entry_id: str,
) -> PreviewValidationResult:
    """Resolve an entry's releases/assets/locations against the live index.

    Returns a read-only preview result. An entry is ``available`` when its
    status is ``published`` and at least one location across its releases
    resolves to an active resource in an enabled content root. Unavailable
    locations are reported with their reason but no state is mutated.
    """
    entry = await state.get(CatalogEntry, entry_id)
    if entry is None:
        raise CatalogEntryNotFound(entry_id)

    roots = await enabled_root_ids(state)
    releases = list(
        (
            await state.scalars(
                select(CatalogRelease)
                .where(CatalogRelease.entry_id == entry_id)
                .order_by(CatalogRelease.sort_order, CatalogRelease.created_at)
            )
        ).all()
    )

    release_payloads: list[dict] = []
    unavailable: list[dict] = []
    any_available = False
    for release in releases:
        assets = list(
            (
                await state.scalars(
                    select(CatalogAsset)
                    .where(CatalogAsset.release_id == release.release_id)
                    .order_by(CatalogAsset.sort_order)
                )
            ).all()
        )
        asset_summaries: list[dict] = []
        for asset in assets:
            locations = list(
                (
                    await state.scalars(
                        select(CatalogLocation).where(
                            CatalogLocation.asset_id == asset.asset_id
                        )
                    )
                ).all()
            )
            asset_available = False
            for loc in locations:
                if asset.status != "active" or loc.status != "active":
                    unavailable.append(
                        {
                            "location_id": loc.location_id,
                            "resource_id": loc.resource_id,
                            "reason": "disabled",
                        }
                    )
                    continue
                resource = await resource_queries(index).catalog_resource(resource_id=loc.resource_id)
                resolution = _resolve_location(
                    resource, loc.resource_id, roots, entry.content_type
                )
                if resolution.available:
                    asset_available = True
                else:
                    unavailable.append(
                        {
                            "location_id": loc.location_id,
                            "resource_id": loc.resource_id,
                            "reason": resolution.reason,
                        }
                    )
            asset_summaries.append(
                {"asset_id": asset.asset_id, "slug": asset.slug, "available": asset_available}
            )
            if asset_available and release.status == "published":
                any_available = True
        release_payloads.append(
            {
                "release_id": release.release_id,
                "slug": release.slug,
                "status": release.status,
                "assets": asset_summaries,
            }
        )

    available = entry.status == "published" and any_available
    return PreviewValidationResult(
        entry_id=entry_id,
        status=entry.status,
        available=available,
        releases=release_payloads,
        unavailable_locations=unavailable,
    )
async def publish_catalog_entry(
    state: AsyncSession,
    index: AsyncSession,
    entry_id: str,
    *,
    expected_revision: int,
    actor: str = "system",
) -> PublishCatalogEntryResult:
    """Publish an entry after validating every active location is in scope.

    Requires ``expected_revision`` to match. All active locations across the
    entry's releases are resolved against the live index and current publication
    scope; if any is missing, inactive, disabled-root, or otherwise unavailable,
    ``CatalogPublishValidationFailed`` is raised before any state mutation, so
    no partial commit is possible. On success the entry status becomes
    ``published``, ``published_at`` is set, and the revision is incremented in
    the same transaction. The default unversioned release is published too if it
    was still in draft.
    """
    entry = await state.get(CatalogEntry, entry_id)
    if entry is None:
        raise CatalogEntryNotFound(entry_id)
    if entry.revision != expected_revision:
        raise CatalogRevisionConflict(entry_id, expected_revision, entry.revision)

    roots = await enabled_root_ids(state)
    reasons = await _collect_location_blockers(
        state, index, entry_id, roots, entry.content_type
    )
    if reasons:
        raise CatalogPublishValidationFailed(entry_id, reasons)

    published_at = utcnow()
    before = _entry_snapshot(entry)
    entry.status = "published"
    entry.published_at = published_at
    entry.revision = entry.revision + 1

    default_release = await state.scalar(
        select(CatalogRelease).where(
            CatalogRelease.entry_id == entry_id,
            CatalogRelease.slug == DEFAULT_RELEASE_SLUG,
        )
    )
    if default_release is not None and default_release.status != "published":
        release_before = {
            "status": default_release.status,
            "published_at": None,
        }
        default_release.status = "published"
        default_release.published_at = published_at
        await append_catalog_revision(
            state,
            target_type="release",
            target_id=default_release.release_id,
            action="publish",
            actor=actor,
            before=release_before,
            after={"status": "published", "published_at": published_at.isoformat()},
        )

    await state.flush()
    after = _entry_snapshot(entry)
    await append_catalog_revision(
        state,
        target_type="entry",
        target_id=entry.entry_id,
        action="publish",
        actor=actor,
        base_revision=expected_revision,
        resulting_revision=entry.revision,
        before=before,
        after=after,
        diff={
            "status": [before["status"], after["status"]],
            "revision": [before["revision"], after["revision"]],
        },
    )
    await enqueue_catalog_search_outbox(state, entry_id=entry.entry_id, revision=entry.revision, action="upsert")
    return PublishCatalogEntryResult(entry=entry, published_at=published_at)
