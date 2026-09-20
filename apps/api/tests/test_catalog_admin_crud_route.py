"""C2 release/asset/location CRUD 路由端到端测试。

覆盖 admin catalog 管理 API：
- 创建/编辑/删除 release、asset、location
- 删除含 asset 的 release → 409 CATALOG_DELETE_CONFLICT
- 推荐版本唯一
"""
from datetime import datetime, timezone

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import auth, main
from cloudsite.database import IndexBase, StateBase
from cloudsite.models import (
    ContentRootMapping,
    Resource,
    SiteSettings,
    SystemSetting,
    utcnow,
)

_RESOURCE_ID = "r_" + "b" * 32


async def _setup(monkeypatch):
    state_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    index_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with state_engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as connection:
        await connection.run_sync(IndexBase.metadata.create_all)
    state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    index_factory = async_sessionmaker(index_engine, expire_on_commit=False)
    async with state_factory() as state:
        state.add_all(
            [
                SiteSettings(id=1),
                SystemSetting(key="setup_completed", value="true", value_type="string"),
                ContentRootMapping(
                    id=1,
                    content_type="software",
                    display_name="Software",
                    alist_path="/software",
                    enabled=True,
                ),
            ]
        )
        await state.commit()
    async with index_factory() as index:
        index.add(
            Resource(
                id=_RESOURCE_ID,
                name="cloudsite-x64.zip",
                path="/software/cloudsite-x64.zip",
                parent_id=None,
                content_type="software",
                root_mapping_id=1,
                extension="zip",
                mime_type="application/zip",
                size=123,
                status="active",
                indexed_at=datetime.now(timezone.utc),
            )
        )
        await index.commit()
    monkeypatch.setattr(main, "StateSession", state_factory)
    monkeypatch.setattr(main, "IndexSession", index_factory)
    monkeypatch.setattr(auth, "StateSession", state_factory)
    return state_engine, index_engine


def _admin_client(transport):
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    client.cookies.set(main.SESSION_COOKIE, main.create_session_token("admin"))
    return client


async def _create_entry(admin):
    created = await admin.post(
        "/api/admin/catalog/entries",
        json={"content_type": "software", "slug": "cloudsite", "title": "CloudSite"},
    )
    assert created.status_code == 201, created.text
    return created.json()["entry_id"]


async def test_release_crud(monkeypatch):
    state_engine, index_engine = await _setup(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with _admin_client(transport) as admin:
            entry_id = await _create_entry(admin)
            created = await admin.post(
                f"/api/admin/catalog/entries/{entry_id}/releases",
                json={"slug": "v1", "title": "Version 1", "channel": "stable"},
            )
            assert created.status_code == 201, created.text
            release_id = created.json()["release_id"]
            assert created.json()["slug"] == "v1"
            assert created.json()["title"] == "Version 1"

            updated = await admin.patch(
                f"/api/admin/catalog/releases/{release_id}",
                json={"title": "Version 1.1", "release_notes": "patch notes"},
            )
            assert updated.status_code == 200, updated.text
            assert updated.json()["title"] == "Version 1.1"
            assert updated.json()["release_notes"] == "patch notes"

            fetched = await admin.get(f"/api/admin/catalog/releases/{release_id}")
            assert fetched.status_code == 200, fetched.text
            assert fetched.json()["title"] == "Version 1.1"

            deleted = await admin.delete(f"/api/admin/catalog/releases/{release_id}")
            assert deleted.status_code == 204, deleted.text

            missing = await admin.get(f"/api/admin/catalog/releases/{release_id}")
            assert missing.status_code == 404, missing.text
    finally:
        await state_engine.dispose()
        await index_engine.dispose()


async def test_asset_crud(monkeypatch):
    state_engine, index_engine = await _setup(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with _admin_client(transport) as admin:
            entry_id = await _create_entry(admin)
            releases = await admin.get(f"/api/admin/catalog/entries/{entry_id}/releases")
            assert releases.status_code == 200, releases.text
            release_id = releases.json()["items"][0]["release_id"]

            created = await admin.post(
                f"/api/admin/catalog/releases/{release_id}/assets",
                json={"slug": "windows-x64", "display_name": "Windows x64", "platform": "windows", "kind": "archive"},
            )
            assert created.status_code == 201, created.text
            asset_id = created.json()["asset_id"]
            assert created.json()["display_name"] == "Windows x64"

            updated = await admin.patch(
                f"/api/admin/catalog/assets/{asset_id}",
                json={"display_name": "Windows x64 (updated)", "architecture": "x64"},
            )
            assert updated.status_code == 200, updated.text
            assert updated.json()["display_name"] == "Windows x64 (updated)"
            assert updated.json()["architecture"] == "x64"

            fetched = await admin.get(f"/api/admin/catalog/assets/{asset_id}")
            assert fetched.status_code == 200, fetched.text
            assert fetched.json()["display_name"] == "Windows x64 (updated)"

            deleted = await admin.delete(f"/api/admin/catalog/assets/{asset_id}")
            assert deleted.status_code == 204, deleted.text

            missing = await admin.get(f"/api/admin/catalog/assets/{asset_id}")
            assert missing.status_code == 404, missing.text
    finally:
        await state_engine.dispose()
        await index_engine.dispose()


async def test_location_crud(monkeypatch):
    state_engine, index_engine = await _setup(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with _admin_client(transport) as admin:
            entry_id = await _create_entry(admin)
            releases = await admin.get(f"/api/admin/catalog/entries/{entry_id}/releases")
            release_id = releases.json()["items"][0]["release_id"]
            created_asset = await admin.post(
                f"/api/admin/catalog/releases/{release_id}/assets",
                json={"slug": "windows-x64", "display_name": "Windows x64"},
            )
            asset_id = created_asset.json()["asset_id"]

            attached = await admin.post(
                f"/api/admin/catalog/assets/{asset_id}/locations",
                json={"resource_id": _RESOURCE_ID, "label": "primary", "is_primary": True},
            )
            assert attached.status_code == 201, attached.text
            location_id = attached.json()["location_id"]
            assert attached.json()["is_primary"] is True
            assert attached.json()["label"] == "primary"

            updated = await admin.patch(
                f"/api/admin/catalog/locations/{location_id}",
                json={"label": "main-mirror"},
            )
            assert updated.status_code == 200, updated.text
            assert updated.json()["label"] == "main-mirror"

            listed = await admin.get(f"/api/admin/catalog/assets/{asset_id}/locations")
            assert listed.status_code == 200, listed.text
            assert listed.json()["items"][0]["location_id"] == location_id

            deleted = await admin.delete(f"/api/admin/catalog/locations/{location_id}")
            assert deleted.status_code == 204, deleted.text

            listed_after = await admin.get(f"/api/admin/catalog/assets/{asset_id}/locations")
            assert listed_after.status_code == 200, listed_after.text
            assert listed_after.json()["items"] == []
    finally:
        await state_engine.dispose()
        await index_engine.dispose()


async def test_delete_release_with_assets_returns_409(monkeypatch):
    state_engine, index_engine = await _setup(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with _admin_client(transport) as admin:
            entry_id = await _create_entry(admin)
            created_release = await admin.post(
                f"/api/admin/catalog/entries/{entry_id}/releases",
                json={"slug": "v2", "title": "Version 2"},
            )
            release_id = created_release.json()["release_id"]
            created_asset = await admin.post(
                f"/api/admin/catalog/releases/{release_id}/assets",
                json={"slug": "linux-x64", "display_name": "Linux x64"},
            )
            assert created_asset.status_code == 201, created_asset.text

            deleted = await admin.delete(f"/api/admin/catalog/releases/{release_id}")
            assert deleted.status_code == 409, deleted.text
            body = deleted.json()["detail"]
            assert body["code"] == "CATALOG_DELETE_CONFLICT"

            removed_asset = await admin.delete(f"/api/admin/catalog/assets/{created_asset.json()['asset_id']}")
            assert removed_asset.status_code == 204, removed_asset.text
            deleted_ok = await admin.delete(f"/api/admin/catalog/releases/{release_id}")
            assert deleted_ok.status_code == 204, deleted_ok.text
    finally:
        await state_engine.dispose()
        await index_engine.dispose()


async def test_recommended_release_uniqueness(monkeypatch):
    state_engine, index_engine = await _setup(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with _admin_client(transport) as admin:
            entry_id = await _create_entry(admin)
            first = await admin.post(
                f"/api/admin/catalog/entries/{entry_id}/releases",
                json={"slug": "v1", "title": "Version 1", "is_recommended": True},
            )
            assert first.status_code == 201, first.text
            assert first.json()["is_recommended"] is True

            second = await admin.post(
                f"/api/admin/catalog/entries/{entry_id}/releases",
                json={"slug": "v2", "title": "Version 2", "is_recommended": True},
            )
            assert second.status_code == 201, second.text

            releases = await admin.get(f"/api/admin/catalog/entries/{entry_id}/releases")
            assert releases.status_code == 200, releases.text
            recommended = [r for r in releases.json()["items"] if r["is_recommended"]]
            assert len(recommended) <= 1, "at most one recommended release per entry"
    finally:
        await state_engine.dispose()
        await index_engine.dispose()
