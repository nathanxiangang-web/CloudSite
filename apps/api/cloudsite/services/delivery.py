"""T2 delivery package service.

Version-explicit delivery packages with content fingerprint verification.
Creates snapshot at publish time; new versions don't change published packages.
Detects content changes before download and rejects stale delivery.

Transaction ownership stays with the caller.
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import CatalogAsset, DeliveryPackage, DeliveryPackageItem, utcnow

PACKAGE_ID_PREFIX = "dp_"
_TOKEN_HEX_LEN = 32
_ACCESS_TOKEN_LEN = 48


class DeliveryError(Exception):
    """Delivery service error base class."""


class PackageNotFound(DeliveryError):
    def __init__(self, package_id: str):
        super().__init__(f"Delivery package {package_id} not found")


class PackageStateInvalid(DeliveryError):
    def __init__(self, message: str):
        super().__init__(message)


class ItemNotFound(DeliveryError):
    def __init__(self, item_id: int):
        super().__init__(f"Delivery item {item_id} not found")


class AccessDenied(DeliveryError):
    def __init__(self, message: str = "Access denied"):
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class PackageSummary:
    package_id: str
    name: str
    project_note: str
    revision: int
    creator_user_id: int | None
    status: str
    expires_at: datetime | None
    published_at: datetime | None
    item_count: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ItemSummary:
    item_id: int
    package_id: str
    asset_id: str | None
    resource_id: str | None
    display_name: str
    bound_checksum: str | None
    bound_checksum_algorithm: str | None
    bound_size: int | None
    sort_order: int
    note: str
    changed: bool


@dataclass(frozen=True, slots=True)
class PackageDetail:
    package: PackageSummary
    items: list[ItemSummary]


def _new_package_id() -> str:
    return PACKAGE_ID_PREFIX + secrets.token_hex(_TOKEN_HEX_LEN // 2)


def _new_access_token() -> str:
    return secrets.token_urlsafe(_ACCESS_TOKEN_LEN)


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


async def create_package(
    state: AsyncSession,
    name: str,
    project_note: str = "",
    creator_user_id: int | None = None,
    access_code: str | None = None,
    expires_at: datetime | None = None,
) -> DeliveryPackage:
    package = DeliveryPackage(
        package_id=_new_package_id(),
        name=name,
        project_note=project_note,
        revision=1,
        creator_user_id=creator_user_id,
        access_token=_new_access_token(),
        code_hash=_hash_code(access_code) if access_code else None,
        expires_at=expires_at,
        status="draft",
    )
    state.add(package)
    await state.flush()
    return package


async def get_package(state: AsyncSession, package_id: str) -> DeliveryPackage:
    package = await state.get(DeliveryPackage, package_id)
    if not package:
        raise PackageNotFound(package_id)
    return package


async def list_packages(
    state: AsyncSession,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[PackageSummary], int]:
    stmt = select(DeliveryPackage).order_by(DeliveryPackage.created_at.desc())
    if status:
        stmt = stmt.where(DeliveryPackage.status == status)
    from sqlalchemy import func
    count_stmt = select(func.count()).select_from(DeliveryPackage)
    if status:
        count_stmt = count_stmt.where(DeliveryPackage.status == status)
    total = await state.scalar(count_stmt) or 0
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    result = await state.execute(stmt)
    packages = result.scalars().all()

    summaries = []
    for p in packages:
        item_count = await state.scalar(
            select(func.count()).select_from(DeliveryPackageItem).where(DeliveryPackageItem.package_id == p.package_id)
        ) or 0
        summaries.append(PackageSummary(
            package_id=p.package_id,
            name=p.name,
            project_note=p.project_note,
            revision=p.revision,
            creator_user_id=p.creator_user_id,
            status=p.status,
            expires_at=p.expires_at,
            published_at=p.published_at,
            item_count=item_count,
            created_at=p.created_at,
            updated_at=p.updated_at,
        ))
    return summaries, total


async def add_item(
    state: AsyncSession,
    package_id: str,
    asset_id: str | None = None,
    resource_id: str | None = None,
    display_name: str = "",
    note: str = "",
    sort_order: int = 0,
) -> DeliveryPackageItem:
    package = await get_package(state, package_id)
    if package.status not in ("draft", "published"):
        raise PackageStateInvalid(f"Cannot add items to {package.status} package")

    bound_checksum = None
    bound_checksum_algorithm = None
    bound_size = None

    if asset_id:
        asset = await state.get(CatalogAsset, asset_id)
        if asset:
            bound_checksum = asset.checksum
            bound_checksum_algorithm = asset.checksum_algorithm
            bound_size = asset.size

    item = DeliveryPackageItem(
        package_id=package_id,
        asset_id=asset_id,
        resource_id=resource_id,
        display_name=display_name,
        bound_checksum=bound_checksum,
        bound_checksum_algorithm=bound_checksum_algorithm,
        bound_size=bound_size,
        sort_order=sort_order,
        note=note,
    )
    state.add(item)
    await state.flush()
    return item


async def remove_item(state: AsyncSession, package_id: str, item_id: int) -> None:
    package = await get_package(state, package_id)
    if package.status not in ("draft", "published"):
        raise PackageStateInvalid(f"Cannot remove items from {package.status} package")
    item = await state.get(DeliveryPackageItem, item_id)
    if not item or item.package_id != package_id:
        raise ItemNotFound(item_id)
    await state.delete(item)
    await state.flush()


async def publish_package(state: AsyncSession, package_id: str) -> DeliveryPackage:
    package = await get_package(state, package_id)
    if package.status != "draft":
        raise PackageStateInvalid(f"Cannot publish {package.status} package")
    package.status = "published"
    package.published_at = utcnow()
    package.updated_at = utcnow()
    await state.flush()
    return package


async def cancel_package(state: AsyncSession, package_id: str, reason: str = "") -> DeliveryPackage:
    package = await get_package(state, package_id)
    if package.status == "cancelled":
        raise PackageStateInvalid("Package already cancelled")
    package.status = "cancelled"
    package.cancelled_at = utcnow()
    package.updated_at = utcnow()
    await state.flush()
    return package


async def get_package_detail(state: AsyncSession, package_id: str) -> PackageDetail:
    package = await get_package(state, package_id)
    result = await state.execute(
        select(DeliveryPackageItem)
        .where(DeliveryPackageItem.package_id == package_id)
        .order_by(DeliveryPackageItem.sort_order)
    )
    items = result.scalars().all()

    item_summaries = []
    for item in items:
        changed = await _check_item_changed(state, item)
        item_summaries.append(ItemSummary(
            item_id=item.item_id,
            package_id=item.package_id,
            asset_id=item.asset_id,
            resource_id=item.resource_id,
            display_name=item.display_name,
            bound_checksum=item.bound_checksum,
            bound_checksum_algorithm=item.bound_checksum_algorithm,
            bound_size=item.bound_size,
            sort_order=item.sort_order,
            note=item.note,
            changed=changed,
        ))

    from sqlalchemy import func
    item_count = await state.scalar(
        select(func.count()).select_from(DeliveryPackageItem).where(DeliveryPackageItem.package_id == package_id)
    ) or 0

    summary = PackageSummary(
        package_id=package.package_id,
        name=package.name,
        project_note=package.project_note,
        revision=package.revision,
        creator_user_id=package.creator_user_id,
        status=package.status,
        expires_at=package.expires_at,
        published_at=package.published_at,
        item_count=item_count,
        created_at=package.created_at,
        updated_at=package.updated_at,
    )
    return PackageDetail(package=summary, items=item_summaries)


async def _check_item_changed(state: AsyncSession, item: DeliveryPackageItem) -> bool:
    if not item.asset_id or not item.bound_checksum:
        return False
    asset = await state.get(CatalogAsset, item.asset_id)
    if not asset:
        return True
    return asset.checksum != item.bound_checksum


async def verify_access(
    state: AsyncSession,
    access_token: str,
    access_code: str | None = None,
) -> DeliveryPackage:
    result = await state.execute(
        select(DeliveryPackage).where(DeliveryPackage.access_token == access_token)
    )
    package = result.scalar_one_or_none()
    if not package:
        raise AccessDenied("Invalid token")
    if package.status != "published":
        raise AccessDenied("Package not available")
    if package.expires_at and package.expires_at < utcnow():
        raise AccessDenied("Package expired")
    if package.code_hash:
        if not access_code:
            raise AccessDenied("Access code required")
        if _hash_code(access_code) != package.code_hash:
            raise AccessDenied("Invalid access code")
    return package


async def export_package(state: AsyncSession, package_id: str) -> dict[str, Any]:
    detail = await get_package_detail(state, package_id)
    return {
        "package_id": detail.package.package_id,
        "name": detail.package.name,
        "project_note": detail.package.project_note,
        "revision": detail.package.revision,
        "status": detail.package.status,
        "published_at": detail.package.published_at.isoformat() if detail.package.published_at else None,
        "created_at": detail.package.created_at.isoformat(),
        "items": [
            {
                "item_id": i.item_id,
                "asset_id": i.asset_id,
                "resource_id": i.resource_id,
                "display_name": i.display_name,
                "bound_checksum": i.bound_checksum,
                "bound_checksum_algorithm": i.bound_checksum_algorithm,
                "bound_size": i.bound_size,
                "changed": i.changed,
                "note": i.note,
            }
            for i in detail.items
        ],
    }