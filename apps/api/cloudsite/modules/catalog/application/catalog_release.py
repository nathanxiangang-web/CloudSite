"""Catalog release/asset/location application services.

Split from services/catalog.py (C2). Pure application services over the
CatalogRelease / CatalogAsset / CatalogLocation state models and the 1.0.0
Resource index. Shared exceptions, helpers, and entry-level primitives are
imported from catalog_entry.py.

No FastAPI or HTTPException is imported here; routers translate the domain
exceptions into HTTP responses at the boundary. Transaction ownership stays
with the caller.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import (
    CatalogAsset,
    CatalogEntry,
    CatalogLocation,
    CatalogRelease,
    Resource,
)
from ....services.catalog_metadata import append_catalog_revision
from ....services.catalog_search_projection import enqueue_catalog_search_outbox
from .catalog_entry import (
    ASSET_ID_PREFIX,
    DEFAULT_RELEASE_SLUG,
    LOCATION_ID_PREFIX,
    RELEASE_ID_PREFIX,
    _UNSET,
    CatalogAssetNotDownloadable,
    CatalogEntryNotFound,
    CatalogError,
    CatalogSlugConflict,
    LocationResolution,
    _new_id,
    _resolve_location,
    enabled_root_ids,
)

class CatalogReleaseNotFound(CatalogError):
    def __init__(self, release_id: str):
        super().__init__(f"catalog release not found: {release_id}")
        self.release_id = release_id


class CatalogAssetNotFound(CatalogError):
    def __init__(self, asset_id: str):
        super().__init__(f"catalog asset not found: {asset_id}")
        self.asset_id = asset_id

class CatalogLocationInvalid(CatalogError):
    def __init__(self, resource_id: str, reason: str):
        super().__init__(f"catalog location invalid: {resource_id} ({reason})")
        self.resource_id = resource_id
        self.reason = reason

@dataclass
class CreateCatalogReleaseResult:
    release: CatalogRelease

@dataclass
class CreateCatalogAssetResult:
    asset: CatalogAsset
@dataclass
class AttachCatalogLocationResult:
    location: CatalogLocation
    resolution: LocationResolution
@dataclass
class AssetDownloadTarget:
    resource_id: str
    location_id: str
    root_mapping_id: int | None

async def _clear_other_recommendations(state: AsyncSession, entry_id: str, keep_release_id: str | None) -> None:
    """Remove the recommended flag from sibling releases so at most one release per entry is recommended.

    The partial unique index ux_catalog_releases_one_recommended_per_entry enforces
    this at the database boundary; this helper keeps the application layer from
    relying on catching IntegrityError and makes the explicit choice atomic.
    """
    siblings = list(
        (
            await state.scalars(
                select(CatalogRelease).where(
                    CatalogRelease.entry_id == entry_id,
                    CatalogRelease.is_recommended.is_(True),
                )
            )
        ).all()
    )
    for sibling in siblings:
        if keep_release_id is None or sibling.release_id != keep_release_id:
            sibling.is_recommended = False
async def create_catalog_release(
    state: AsyncSession,
    *,
    entry_id: str,
    slug: str,
    title: str,
    release_notes: str = "",
    channel: str = "unknown",
    release_date: datetime | None = None,
    is_recommended: bool = False,
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
    if is_recommended:
        await _clear_other_recommendations(state, entry_id, None)
    release = CatalogRelease(
        release_id=release_id or _new_id(RELEASE_ID_PREFIX),
        entry_id=entry_id,
        slug=slug,
        title=title,
        release_notes=release_notes,
        status="draft",
        sort_order=sort_order,
        channel=channel or "unknown",
        release_date=release_date,
        is_recommended=bool(is_recommended),
    )
    state.add(release)
    await state.flush()
    await append_catalog_revision(
        state,
        target_type="release",
        target_id=release.release_id,
        action="create",
        actor=actor,
        after={
            "entry_id": entry_id,
            "slug": slug,
            "title": title,
            "release_notes": release_notes,
            "channel": release.channel,
            "release_date": release_date.isoformat() if release_date else None,
            "is_recommended": release.is_recommended,
            "status": release.status,
            "sort_order": sort_order,
        },
    )
    return CreateCatalogReleaseResult(release=release)
async def create_catalog_asset(
    state: AsyncSession,
    *,
    release_id: str,
    slug: str,
    display_name: str,
    platform: str = "",
    kind: str = "file",
    architecture: str = "unknown",
    package_type: str = "unknown",
    language: str = "unknown",
    build_label: str = "",
    checksum: str | None = None,
    checksum_algorithm: str | None = None,
    size: int | None = None,
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
        architecture=architecture or "unknown",
        package_type=package_type or "unknown",
        language=language or "unknown",
        build_label=build_label or "",
        checksum=checksum,
        checksum_algorithm=checksum_algorithm,
        size=size,
        status="active",
        sort_order=sort_order,
    )
    state.add(asset)
    await state.flush()
    await append_catalog_revision(
        state,
        target_type="asset",
        target_id=asset.asset_id,
        action="create",
        actor=actor,
        after={
            "release_id": release_id,
            "slug": slug,
            "display_name": display_name,
            "platform": platform,
            "kind": kind,
            "architecture": asset.architecture,
            "package_type": asset.package_type,
            "language": asset.language,
            "build_label": asset.build_label,
            "status": asset.status,
            "sort_order": sort_order,
        },
    )
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
    await append_catalog_revision(
        state,
        target_type="location",
        target_id=location.location_id,
        action="create",
        actor=actor,
        after={
            "asset_id": asset_id,
            "resource_id": resource_id,
            "root_mapping_id": resolution.root_mapping_id,
            "label": label,
            "is_primary": is_primary,
            "status": location.status,
        },
    )
    _attach_release = await state.get(CatalogRelease, asset.release_id)
    if _attach_release is not None:
        _attach_entry = await state.get(CatalogEntry, _attach_release.entry_id)
        if _attach_entry is not None:
            await enqueue_catalog_search_outbox(state, entry_id=_attach_entry.entry_id, revision=_attach_entry.revision, action="upsert")
    return AttachCatalogLocationResult(location=location, resolution=resolution)
def _release_snapshot(release: CatalogRelease) -> dict:
    return {
        "slug": release.slug,
        "title": release.title,
        "release_notes": release.release_notes,
        "status": release.status,
        "sort_order": release.sort_order,
        "channel": release.channel,
        "release_date": release.release_date.isoformat() if release.release_date else None,
        "is_recommended": release.is_recommended,
    }


def _asset_snapshot(asset: CatalogAsset) -> dict:
    return {
        "slug": asset.slug,
        "display_name": asset.display_name,
        "platform": asset.platform,
        "kind": asset.kind,
        "architecture": asset.architecture,
        "package_type": asset.package_type,
        "language": asset.language,
        "build_label": asset.build_label,
        "checksum": asset.checksum,
        "checksum_algorithm": asset.checksum_algorithm,
        "size": asset.size,
        "status": asset.status,
        "sort_order": asset.sort_order,
    }
async def get_catalog_release(state: AsyncSession, release_id: str) -> CatalogRelease:
    release = await state.get(CatalogRelease, release_id)
    if release is None:
        raise CatalogReleaseNotFound(release_id)
    return release


async def get_catalog_asset(state: AsyncSession, asset_id: str) -> CatalogAsset:
    asset = await state.get(CatalogAsset, asset_id)
    if asset is None:
        raise CatalogAssetNotFound(asset_id)
    return asset


async def list_catalog_releases(
    state: AsyncSession,
    entry_id: str,
) -> list[CatalogRelease]:
    return list(
        (
            await state.scalars(
                select(CatalogRelease)
                .where(CatalogRelease.entry_id == entry_id)
                .order_by(CatalogRelease.sort_order, CatalogRelease.created_at)
            )
        ).all()
    )


async def list_catalog_assets(
    state: AsyncSession,
    release_id: str,
) -> list[CatalogAsset]:
    return list(
        (
            await state.scalars(
                select(CatalogAsset)
                .where(CatalogAsset.release_id == release_id)
                .order_by(CatalogAsset.sort_order, CatalogAsset.created_at)
            )
        ).all()
    )


async def list_catalog_locations(
    state: AsyncSession,
    asset_id: str,
) -> list[CatalogLocation]:
    return list(
        (
            await state.scalars(
                select(CatalogLocation)
                .where(CatalogLocation.asset_id == asset_id)
                .order_by(CatalogLocation.is_primary.desc(), CatalogLocation.created_at)
            )
        ).all()
    )
async def update_catalog_release(
    state: AsyncSession,
    release_id: str,
    *,
    slug: str | object = _UNSET,
    title: str | object = _UNSET,
    release_notes: str | object = _UNSET,
    channel: str | object = _UNSET,
    release_date: datetime | None | object = _UNSET,
    is_recommended: bool | object = _UNSET,
    status: str | object = _UNSET,
    sort_order: int | object = _UNSET,
    actor: str = "system",
) -> CatalogRelease:
    release = await state.get(CatalogRelease, release_id)
    if release is None:
        raise CatalogReleaseNotFound(release_id)
    before = _release_snapshot(release)
    changed = False
    if slug is not _UNSET and release.slug != slug:
        existing = await state.scalar(
            select(CatalogRelease).where(
                CatalogRelease.entry_id == release.entry_id,
                CatalogRelease.slug == slug,
                CatalogRelease.release_id != release_id,
            )
        )
        if existing is not None:
            raise CatalogSlugConflict(str(slug))
        release.slug = slug  # type: ignore[assignment]
        changed = True
    if title is not _UNSET and release.title != title:
        release.title = title  # type: ignore[assignment]
        changed = True
    if release_notes is not _UNSET and release.release_notes != release_notes:
        release.release_notes = release_notes  # type: ignore[assignment]
        changed = True
    if channel is not _UNSET and release.channel != channel:
        release.channel = channel or "unknown"  # type: ignore[assignment]
        changed = True
    if release_date is not _UNSET and release.release_date != release_date:
        release.release_date = release_date  # type: ignore[assignment]
        changed = True
    if is_recommended is not _UNSET and release.is_recommended != bool(is_recommended):
        if is_recommended:
            await _clear_other_recommendations(state, release.entry_id, release_id)
        release.is_recommended = bool(is_recommended)  # type: ignore[assignment]
        changed = True
    if status is not _UNSET and release.status != status:
        release.status = status  # type: ignore[assignment]
        changed = True
    if sort_order is not _UNSET and release.sort_order != sort_order:
        release.sort_order = sort_order  # type: ignore[assignment]
        changed = True
    if changed:
        await state.flush()
        after = _release_snapshot(release)
        diff = {
            key: [before.get(key), after.get(key)]
            for key in after
            if before.get(key) != after.get(key)
        }
        await append_catalog_revision(
            state,
            target_type="release",
            target_id=release.release_id,
            action="update",
            actor=actor,
            before=before,
            after=after,
            diff=diff,
        )
    if before.get("status") != "published" and release.status == "published":
        from ....services.catalog_follow import notify_release_subscribers  # noqa: PLC0415

        entry = await state.get(CatalogEntry, release.entry_id)
        if entry is not None and entry.status == "published":
            await notify_release_subscribers(state, release=release, entry=entry)
    return release
async def update_catalog_asset(
    state: AsyncSession,
    asset_id: str,
    *,
    slug: str | object = _UNSET,
    display_name: str | object = _UNSET,
    platform: str | object = _UNSET,
    kind: str | object = _UNSET,
    architecture: str | object = _UNSET,
    package_type: str | object = _UNSET,
    language: str | object = _UNSET,
    build_label: str | object = _UNSET,
    checksum: str | None | object = _UNSET,
    checksum_algorithm: str | None | object = _UNSET,
    size: int | None | object = _UNSET,
    status: str | object = _UNSET,
    sort_order: int | object = _UNSET,
    actor: str = "system",
) -> CatalogAsset:
    asset = await state.get(CatalogAsset, asset_id)
    if asset is None:
        raise CatalogAssetNotFound(asset_id)
    before = _asset_snapshot(asset)
    changed = False
    if slug is not _UNSET and asset.slug != slug:
        existing = await state.scalar(
            select(CatalogAsset).where(
                CatalogAsset.release_id == asset.release_id,
                CatalogAsset.slug == slug,
                CatalogAsset.asset_id != asset_id,
            )
        )
        if existing is not None:
            raise CatalogSlugConflict(str(slug))
        asset.slug = slug  # type: ignore[assignment]
        changed = True
    if display_name is not _UNSET and asset.display_name != display_name:
        asset.display_name = display_name  # type: ignore[assignment]
        changed = True
    if platform is not _UNSET and asset.platform != platform:
        asset.platform = platform  # type: ignore[assignment]
        changed = True
    if kind is not _UNSET and asset.kind != kind:
        asset.kind = kind  # type: ignore[assignment]
        changed = True
    if architecture is not _UNSET and asset.architecture != architecture:
        asset.architecture = architecture or "unknown"  # type: ignore[assignment]
        changed = True
    if package_type is not _UNSET and asset.package_type != package_type:
        asset.package_type = package_type or "unknown"  # type: ignore[assignment]
        changed = True
    if language is not _UNSET and asset.language != language:
        asset.language = language or "unknown"  # type: ignore[assignment]
        changed = True
    if build_label is not _UNSET and asset.build_label != build_label:
        asset.build_label = build_label or ""  # type: ignore[assignment]
        changed = True
    if checksum is not _UNSET and asset.checksum != checksum:
        asset.checksum = checksum  # type: ignore[assignment]
        changed = True
    if checksum_algorithm is not _UNSET and asset.checksum_algorithm != checksum_algorithm:
        asset.checksum_algorithm = checksum_algorithm  # type: ignore[assignment]
        changed = True
    if size is not _UNSET and asset.size != size:
        asset.size = size  # type: ignore[assignment]
        changed = True
    if status is not _UNSET and asset.status != status:
        asset.status = status  # type: ignore[assignment]
        changed = True
    if sort_order is not _UNSET and asset.sort_order != sort_order:
        asset.sort_order = sort_order  # type: ignore[assignment]
        changed = True
    if changed:
        await state.flush()
        after = _asset_snapshot(asset)
        diff = {
            key: [before.get(key), after.get(key)]
            for key in after
            if before.get(key) != after.get(key)
        }
        await append_catalog_revision(
            state,
            target_type="asset",
            target_id=asset.asset_id,
            action="update",
            actor=actor,
            before=before,
            after=after,
            diff=diff,
        )
    return asset
async def update_catalog_location(
    state: AsyncSession,
    location_id: str,
    *,
    label: str | object = _UNSET,
    is_primary: bool | object = _UNSET,
    status: str | object = _UNSET,
    actor: str = "system",
) -> CatalogLocation:
    location = await state.get(CatalogLocation, location_id)
    if location is None:
        raise CatalogLocationInvalid(location_id, "not_found")
    before = {
        "label": location.label,
        "is_primary": location.is_primary,
        "status": location.status,
    }
    changed = False
    if label is not _UNSET and location.label != label:
        location.label = label  # type: ignore[assignment]
        changed = True
    if is_primary is not _UNSET and location.is_primary != bool(is_primary):
        if is_primary:
            current_primaries = list(
                (
                    await state.scalars(
                        select(CatalogLocation).where(
                            CatalogLocation.asset_id == location.asset_id,
                            CatalogLocation.is_primary.is_(True),
                            CatalogLocation.location_id != location_id,
                        )
                    )
                ).all()
            )
            for loc in current_primaries:
                loc.is_primary = False
        location.is_primary = bool(is_primary)  # type: ignore[assignment]
        changed = True
    if status is not _UNSET and location.status != status:
        location.status = status  # type: ignore[assignment]
        changed = True
    if changed:
        await state.flush()
        after = {
            "label": location.label,
            "is_primary": location.is_primary,
            "status": location.status,
        }
        await append_catalog_revision(
            state,
            target_type="location",
            target_id=location.location_id,
            action="update",
            actor=actor,
            before=before,
            after=after,
        )
    return location
async def delete_catalog_location(
    state: AsyncSession,
    location_id: str,
    *,
    actor: str = "system",
) -> None:
    location = await state.get(CatalogLocation, location_id)
    if location is None:
        raise CatalogLocationInvalid(location_id, "not_found")
    before = {
        "asset_id": location.asset_id,
        "resource_id": location.resource_id,
        "is_primary": location.is_primary,
        "status": location.status,
    }
    await state.delete(location)
    await state.flush()
    await append_catalog_revision(
        state,
        target_type="location",
        target_id=location_id,
        action="delete",
        actor=actor,
        before=before,
    )
async def resolve_asset_download_target(
    state: AsyncSession,
    index: AsyncSession,
    entry_id: str,
    asset_id: str,
) -> AssetDownloadTarget:
    """Resolve a catalog asset to a single downloadable location resource.

    Validates the entry is published, the owning release is published, the asset
    is active, and at least one enabled location references an active resource in
    an enabled content root with a matching content type. A primary location is
    preferred<|endoftext|>preferred; otherwise the first available location is used. The caller
    (HTTP layer) is responsible for rate limiting, audit, and the actual 302
    redirect via the existing 1.0.0 transfer path. No client-provided mirror URL
    is ever accepted.
    """
    entry = await state.get(CatalogEntry, entry_id)
    if entry is None or entry.status != "published":
        raise CatalogAssetNotDownloadable(asset_id, "entry_not_published")
    asset = await state.get(CatalogAsset, asset_id)
    if asset is None:
        raise CatalogAssetNotDownloadable(asset_id, "asset_not_found")
    release = await state.get(CatalogRelease, asset.release_id)
    if release is None or release.entry_id != entry_id:
        raise CatalogAssetNotDownloadable(asset_id, "asset_not_in_entry")
    if release.status != "published":
        raise CatalogAssetNotDownloadable(asset_id, "release_not_published")
    if asset.status != "active":
        raise CatalogAssetNotDownloadable(asset_id, "asset_disabled")
    roots = await enabled_root_ids(state)
    locations = list(
        (
            await state.scalars(
                select(CatalogLocation)
                .where(
                    CatalogLocation.asset_id == asset_id,
                    CatalogLocation.status == "active",
                )
                .order_by(CatalogLocation.is_primary.desc(), CatalogLocation.created_at)
            )
        ).all()
    )
    if not locations:
        raise CatalogAssetNotDownloadable(asset_id, "no_enabled_location")
    chosen: CatalogLocation | None = None
    for location in locations:
        resource = await index.get(Resource, location.resource_id)
        resolution = _resolve_location(resource, location.resource_id, roots, entry.content_type)
        if resolution.available:
            chosen = location
            break
    if chosen is None:
        raise CatalogAssetNotDownloadable(asset_id, "no_available_location")
    return AssetDownloadTarget(
        resource_id=chosen.resource_id,
        location_id=chosen.location_id,
        root_mapping_id=chosen.root_mapping_id,
    )
