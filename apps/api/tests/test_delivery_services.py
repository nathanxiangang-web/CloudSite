"""T2 delivery package service tests.

Covers: create package, add/remove items, publish, cancel, verify access,
content change detection, export, idempotency and state transitions.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from cloudsite.database import StateBase
from cloudsite.models import CatalogAsset, CatalogEntry, CatalogRelease, DeliveryPackage, DeliveryPackageItem
from cloudsite.services import delivery


@pytest.fixture
async def state_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    yield factory
    await engine.dispose()


def _now():
    return datetime.now(timezone.utc)


def _make_asset(asset_id="ca_testasset000000000000000001", checksum="abc123"):
    return CatalogAsset(
        asset_id=asset_id,
        release_id="cr_testrelease0000000000000001",
        slug="test-asset",
        display_name="Test Asset",
        platform="x64",
        kind="installer",
        architecture="x64",
        checksum=checksum,
        checksum_algorithm="sha256",
        size=1024,
        status="active",
    )


async def test_create_package(state_session):
    async with state_session() as state:
        pkg = await delivery.create_package(state, "My Package", "Project note")
        await state.commit()
        assert pkg.package_id.startswith("dp_")
        assert pkg.name == "My Package"
        assert pkg.status == "draft"
        assert pkg.revision == 1
        assert pkg.access_token is not None
        assert len(pkg.access_token) > 0


async def test_create_package_with_code(state_session):
    async with state_session() as state:
        pkg = await delivery.create_package(state, "Secure Package", access_code="1234")
        await state.commit()
        assert pkg.code_hash is not None
        assert pkg.code_hash != "1234"


async def test_get_package_not_found(state_session):
    async with state_session() as state:
        with pytest.raises(delivery.PackageNotFound):
            await delivery.get_package(state, "dp_nonexistent")


async def test_list_packages(state_session):
    async with state_session() as state:
        await delivery.create_package(state, "Package A")
        await delivery.create_package(state, "Package B")
        await state.commit()
        items, total = await delivery.list_packages(state)
        assert total == 2
        assert items[0].name in ("Package A", "Package B")


async def test_list_packages_filter_by_status(state_session):
    async with state_session() as state:
        pkg = await delivery.create_package(state, "Draft")
        await delivery.create_package(state, "Also Draft")
        await state.commit()
        items, total = await delivery.list_packages(state, status="draft")
        assert total == 2
        items, total = await delivery.list_packages(state, status="published")
        assert total == 0


async def test_add_item(state_session):
    async with state_session() as state:
        pkg = await delivery.create_package(state, "Test")
        item = await delivery.add_item(state, pkg.package_id, display_name="Item 1", sort_order=1)
        await state.commit()
        assert item.display_name == "Item 1"
        assert item.package_id == pkg.package_id


async def test_add_item_binds_checksum(state_session):
    async with state_session() as state:
        asset = _make_asset()
        state.add(asset)
        await state.flush()
        pkg = await delivery.create_package(state, "Test")
        item = await delivery.add_item(state, pkg.package_id, asset_id=asset.asset_id, display_name="Asset Item")
        await state.commit()
        assert item.bound_checksum == "abc123"
        assert item.bound_checksum_algorithm == "sha256"
        assert item.bound_size == 1024


async def test_remove_item(state_session):
    async with state_session() as state:
        pkg = await delivery.create_package(state, "Test")
        item = await delivery.add_item(state, pkg.package_id, display_name="Item")
        await state.commit()
        await delivery.remove_item(state, pkg.package_id, item.item_id)
        await state.commit()
        detail = await delivery.get_package_detail(state, pkg.package_id)
        assert len(detail.items) == 0


async def test_publish_package(state_session):
    async with state_session() as state:
        pkg = await delivery.create_package(state, "Test")
        await state.commit()
        published = await delivery.publish_package(state, pkg.package_id)
        await state.commit()
        assert published.status == "published"
        assert published.published_at is not None


async def test_publish_non_draft_fails(state_session):
    async with state_session() as state:
        pkg = await delivery.create_package(state, "Test")
        await delivery.publish_package(state, pkg.package_id)
        await state.commit()
        with pytest.raises(delivery.PackageStateInvalid):
            await delivery.publish_package(state, pkg.package_id)


async def test_cancel_package(state_session):
    async with state_session() as state:
        pkg = await delivery.create_package(state, "Test")
        await delivery.publish_package(state, pkg.package_id)
        await state.commit()
        cancelled = await delivery.cancel_package(state, pkg.package_id)
        await state.commit()
        assert cancelled.status == "cancelled"
        assert cancelled.cancelled_at is not None


async def test_cancel_already_cancelled_fails(state_session):
    async with state_session() as state:
        pkg = await delivery.create_package(state, "Test")
        await delivery.cancel_package(state, pkg.package_id)
        await state.commit()
        with pytest.raises(delivery.PackageStateInvalid):
            await delivery.cancel_package(state, pkg.package_id)


async def test_verify_access(state_session):
    async with state_session() as state:
        pkg = await delivery.create_package(state, "Test")
        await delivery.publish_package(state, pkg.package_id)
        await state.commit()
        result = await delivery.verify_access(state, pkg.access_token)
        assert result.package_id == pkg.package_id


async def test_verify_access_draft_denied(state_session):
    async with state_session() as state:
        pkg = await delivery.create_package(state, "Test")
        await state.commit()
        with pytest.raises(delivery.AccessDenied):
            await delivery.verify_access(state, pkg.access_token)


async def test_verify_access_cancelled_denied(state_session):
    async with state_session() as state:
        pkg = await delivery.create_package(state, "Test")
        await delivery.publish_package(state, pkg.package_id)
        await delivery.cancel_package(state, pkg.package_id)
        await state.commit()
        with pytest.raises(delivery.AccessDenied):
            await delivery.verify_access(state, pkg.access_token)


async def test_verify_access_with_code(state_session):
    async with state_session() as state:
        pkg = await delivery.create_package(state, "Test", access_code="1234")
        await delivery.publish_package(state, pkg.package_id)
        await state.commit()
        with pytest.raises(delivery.AccessDenied):
            await delivery.verify_access(state, pkg.access_token)
        with pytest.raises(delivery.AccessDenied):
            await delivery.verify_access(state, pkg.access_token, access_code="wrong")
        result = await delivery.verify_access(state, pkg.access_token, access_code="1234")
        assert result.package_id == pkg.package_id


async def test_verify_access_expired(state_session):
    async with state_session() as state:
        past = _now() - timedelta(hours=1)
        pkg = await delivery.create_package(state, "Test", expires_at=past)
        await delivery.publish_package(state, pkg.package_id)
        await state.commit()
        with pytest.raises(delivery.AccessDenied):
            await delivery.verify_access(state, pkg.access_token)


async def test_content_change_detection(state_session):
    async with state_session() as state:
        asset = _make_asset(checksum="original")
        state.add(asset)
        await state.flush()
        pkg = await delivery.create_package(state, "Test")
        await delivery.add_item(state, pkg.package_id, asset_id=asset.asset_id, display_name="Asset")
        await state.commit()

        asset.checksum = "changed"
        await state.flush()

        detail = await delivery.get_package_detail(state, pkg.package_id)
        assert len(detail.items) == 1
        assert detail.items[0].changed is True


async def test_content_no_change(state_session):
    async with state_session() as state:
        asset = _make_asset(checksum="stable")
        state.add(asset)
        await state.flush()
        pkg = await delivery.create_package(state, "Test")
        await delivery.add_item(state, pkg.package_id, asset_id=asset.asset_id, display_name="Asset")
        await state.commit()

        detail = await delivery.get_package_detail(state, pkg.package_id)
        assert detail.items[0].changed is False


async def test_export_package(state_session):
    async with state_session() as state:
        pkg = await delivery.create_package(state, "Export Test", "Project note")
        await delivery.add_item(state, pkg.package_id, display_name="Item 1")
        await state.commit()
        data = await delivery.export_package(state, pkg.package_id)
        assert data["name"] == "Export Test"
        assert data["project_note"] == "Project note"
        assert len(data["items"]) == 1


async def test_get_package_detail(state_session):
    async with state_session() as state:
        pkg = await delivery.create_package(state, "Detail Test")
        await delivery.add_item(state, pkg.package_id, display_name="A", sort_order=2)
        await delivery.add_item(state, pkg.package_id, display_name="B", sort_order=1)
        await state.commit()
        detail = await delivery.get_package_detail(state, pkg.package_id)
        assert detail.package.name == "Detail Test"
        assert len(detail.items) == 2
        assert detail.items[0].sort_order <= detail.items[1].sort_order


async def test_add_item_to_cancelled_fails(state_session):
    async with state_session() as state:
        pkg = await delivery.create_package(state, "Test")
        await delivery.cancel_package(state, pkg.package_id)
        await state.commit()
        with pytest.raises(delivery.PackageStateInvalid):
            await delivery.add_item(state, pkg.package_id, display_name="X")