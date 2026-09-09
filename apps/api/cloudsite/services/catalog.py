"""Catalog C1 application layer: create, edit, bind, preview, publish.

Pure application services over the CatalogEntry / CatalogRelease /
CatalogAsset / CatalogLocation state models and the 1.0.0 Resource index.
No FastAPI or HTTPException is imported here; routers translate the domain
exceptions into HTTP responses at the boundary.

Transaction ownership stays with the caller. Every function accepts the state
and index AsyncSession objects and only flushes within them; the caller commits
or rolls back. A function that needs atomicity across multiple state rows
(e.g. create entry + default release) writes both rows in the same session
transaction and flushes once, so a caller rollback undoes both.

Per docs/catalog-v1.1-contract.md:
- catalog_locations.resource_id is a stable 1.0.0 resource identity stored by
  value; no client-provided download URL is ever accepted.
- Binding and publish validation use server-side index lookup and the current
  publication scope (enabled content roots) and reject missing, inactive,
  disabled-root, or content-type-mismatched files.
- Publishing is a necessary but not sufficient condition for public
  availability; it never changes the visibility of the underlying resource.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    CatalogAsset,
    CatalogEntry,
    CatalogLocation,
    CatalogRelease,
    ContentRootMapping,
    Resource,
    utcnow,
)

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


class CatalogError(Exception):
    """Base class for catalog application-layer errors."""


class CatalogEntryNotFound(CatalogError):
    def __init__(self, entry_id: str):
        super().__init__(f"catalog entry not found: {entry_id}")
        self.entry_id = entry_id


class CatalogReleaseNotFound(CatalogError):
    def __init__(self, release_id: str):
        super().__init__(f"catalog release not found: {release_id}")
        self.release_id = release_id


class CatalogAssetNotFound(CatalogError):
    def __init__(self, asset_id: str):
        super().__init__(f"catalog asset not found: {asset_id}")
        self.asset_id = asset_id


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


class CatalogLocationInvalid(CatalogError):
    def __init__(self, resource_id: str, reason: str):
        super().__init__(f"catalog location invalid: {resource_id} ({reason})")
        self.resource_id = resource_id
        self.reason = reason


class CatalogPublishValidationFailed(CatalogError):
    def __init__(self, entry_id: str, reasons: list[str]):
        super().__init__(f"publish validation failed for {entry_id}")
        self.entry_id = entry_id
        self.reasons = reasons


@dataclass
class CreateCatalogEntryResult:
    entry: CatalogEntry
    release: CatalogRelease


@dataclass
class CreateCatalogReleaseResult:
    release: CatalogRelease


@dataclass
class CreateCatalogAssetResult:
    asset: CatalogAsset


@dataclass
class LocationResolution:
    resource_id: str
    root_mapping_id: int | None
    available: bool
    reason: str = ""


@dataclass
class AttachCatalogLocationResult:
    location: CatalogLocation
    resolution: LocationResolution


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


async def enabled_root_ids(state: AsyncSession) -> set[int]:
    """Return the set of currently enabled content root mapping ids."""
    return set(
        (
            await state.scalars(
                select(ContentRootMapping.id).where(
                    ContentRootMapping.enabled.is_(True)
                )
            )
        ).all()
    )


def _resolve_location(
    resource: Resource | None,
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

    changed = False
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
    return entry


async def create_catalog_release(
    state: AsyncSession,
    *,
    entry_id: str,
    slug: str,
    title: str,
    release_notes: str = "",
    sort_order: int = 0,
    actor: str = "system",
    release_id: str | None = None,
) -> CreateCatalogReleaseResult:
    entry = await state.get(CatalogEntry, entry_id)
    if entry is None:
        raise CatalogEntryNotFound(entry_id)
    existing = await state.scalar(
        select(CatalogRelease).where(
            CatalogRelease.entry_id == entry_id, CatalogRelease.slug == slug
        )
    )
    if existing is not None:
        raise CatalogSlugConflict(slug)
    release = CatalogRelease(
        release_id=release_id or _new_id(RELEASE_ID_PREFIX),
        entry_id=entry_id,
        slug=slug,
        title=title,
        release_notes=release_notes,
        status="draft",
        sort_order=sort_order,
    )
    state.add(release)
    await state.flush()
    return CreateCatalogReleaseResult(release=release)


async def create_catalog_asset(
    state: AsyncSession,
    *,
    release_id: str,
    slug: str,
    display_name: str,
    platform: str = "",
    kind: str = "file",
    sort_order: int = 0,
    actor: str = "system",
    asset_id: str | None = None,
) -> CreateCatalogAssetResult:
    release = await state.get(CatalogRelease, release_id)
    if release is None:
        raise CatalogReleaseNotFound(release_id)
    existing = await state.scalar(
        select(CatalogAsset).where(
            CatalogAsset.release_id == release_id, CatalogAsset.slug == slug
        )
    )
    if existing is not None:
        raise CatalogSlugConflict(slug)
    asset = CatalogAsset(
        asset_id=asset_id or _new_id(ASSET_ID_PREFIX),
        release_id=release_id,
        slug=slug,
        display_name=display_name,
        platform=platform,
        kind=kind,
        status="active",
        sort_order=sort_order,
    )
    state.add(asset)
    await state.flush()
    return CreateCatalogAssetResult(asset=asset)


async def _entry_content_type_for_asset(
    state: AsyncSession, asset: CatalogAsset
) -> str | None:
    release = await state.get(CatalogRelease, asset.release_id)
    if release is None:
        return None
    entry = await state.get(CatalogEntry, release.entry_id)
    return entry.content_type if entry is not None else None


async def attach_catalog_location(
    state: AsyncSession,
    index: AsyncSession,
    *,
    asset_id: str,
    resource_id: str,
    label: str = "",
    is_primary: bool = False,
    actor: str = "system",
    location_id: str | None = None,
) -> AttachCatalogLocationResult:
    """Bind an existing indexed file to an asset as a location.

    The resource is resolved by server-side index lookup. A location is rejected
    when the resource is missing, inactive, belongs to a disabled content root,
    or has a content type that does not match the entry's content type. Only the
    stable ``resource_id`` plus explicit metadata (label, is_primary) and the
    denormalized ``root_mapping_id`` are stored; no client-provided download URL
    is ever accepted.
    """
    asset = await state.get(CatalogAsset, asset_id)
    if asset is None:
        raise CatalogAssetNotFound(asset_id)

    existing_pair = await state.scalar(
        select(CatalogLocation).where(
            CatalogLocation.asset_id == asset_id,
            CatalogLocation.resource_id == resource_id,
        )
    )
    if existing_pair is not None:
        raise CatalogLocationInvalid(resource_id, "duplicate")

    resource = await index.get(Resource, resource_id)
    roots = await enabled_root_ids(state)
    expected_ct = await _entry_content_type_for_asset(state, asset)
    resolution = _resolve_location(resource, resource_id, roots, expected_ct)
    if not resolution.available:
        raise CatalogLocationInvalid(resource_id, resolution.reason)

    if is_primary:
        current_primaries = list(
            (
                await state.scalars(
                    select(CatalogLocation).where(
                        CatalogLocation.asset_id == asset_id,
                        CatalogLocation.is_primary.is_(True),
                    )
                )
            ).all()
        )
        for loc in current_primaries:
            loc.is_primary = False

    location = CatalogLocation(
        location_id=location_id or _new_id(LOCATION_ID_PREFIX),
        asset_id=asset_id,
        resource_id=resource_id,
        root_mapping_id=resolution.root_mapping_id,
        label=label,
        is_primary=is_primary,
        status="active",
    )
    state.add(location)
    await state.flush()
    return AttachCatalogLocationResult(location=location, resolution=resolution)


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
                resource = await index.get(Resource, loc.resource_id)
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
                resource = await index.get(Resource, loc.resource_id)
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
        default_release.status = "published"
        default_release.published_at = published_at

    await state.flush()
    return PublishCatalogEntryResult(entry=entry, published_at=published_at)
