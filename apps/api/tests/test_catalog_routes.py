"""Focused checks for the real C1 Catalog HTTP/application integration."""
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import auth, main
from cloudsite.catalog_schemas import CatalogEntryPublishInput, CatalogLocationBindInput
from cloudsite.database import IndexBase, StateBase
from cloudsite.models import (
    ContentRootMapping,
    Resource,
    SiteSettings,
    SystemSetting,
    User,
    utcnow,
)
from cloudsite.services.catalog import create_catalog_asset
from cloudsite.sessions import USER_SESSION_COOKIE, create_user_session


def _iter_routes(source):
    for route in getattr(source, "routes", []):
        original = getattr(route, "original_router", None)
        if original is not None and not hasattr(route, "path"):
            yield from _iter_routes(original)
        else:
            yield route


def test_catalog_routes_registered():
    found: dict[str, set[str]] = {}
    for route in _iter_routes(main.app):
        path = getattr(route, "path", "")
        if "catalog" not in path:
            continue
        found.setdefault(path, set()).update(
            method
            for method in (getattr(route, "methods", None) or set())
            if method not in {"HEAD", "OPTIONS"}
        )
    assert found["/api/catalog"] == {"GET"}
    assert found["/api/catalog/{entry_id}"] == {"GET"}
    assert found["/api/admin/catalog"] == {"GET", "POST"}
    assert found["/api/admin/catalog/{entry_id}"] == {"GET", "PUT"}
    assert found["/api/admin/catalog/entries"] == {"GET", "POST"}
    assert found["/api/admin/catalog/entries/{entry_id}"] == {"GET", "PATCH"}
    assert found["/api/admin/catalog/entries/{entry_id}/publish"] == {"POST"}
    assert found["/api/admin/catalog/{entry_id}/locations"] == {"POST"}
    assert found["/api/admin/catalog/{entry_id}/preview"] == {"POST"}
    assert found["/api/admin/catalog/{entry_id}/publish"] == {"POST"}


def test_catalog_inputs_require_revision_and_stable_ids():
    with pytest.raises(Exception):
        CatalogEntryPublishInput(expected_revision=0)
    assert CatalogEntryPublishInput(expected_revision=3).expected_revision == 3
    valid = CatalogLocationBindInput(
        asset_id="ca_" + "a" * 32,
        resource_id="r_" + "b" * 32,
    )
    assert valid.resource_id.startswith("r_")
    with pytest.raises(Exception):
        CatalogLocationBindInput(
            asset_id=valid.asset_id,
            resource_id=valid.resource_id,
            upstream_url="https://invalid.example/file",
        )


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
        user = User(
            username="reader",
            username_normalized="reader",
            password_hash="x",
            status="active",
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        state.add(user)
        await state.flush()
        _, user_token = await create_user_session(state, user.id, utcnow())
        await state.commit()
    async with index_factory() as index:
        index.add(
            Resource(
                id="r_" + "b" * 32,
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
    return state_engine, index_engine, state_factory, user_token


async def test_real_create_bind_publish_and_public_read(monkeypatch):
    state_engine, index_engine, state_factory, user_token = await _setup(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as admin:
        admin.cookies.set(main.SESSION_COOKIE, main.create_session_token("admin"))
        created = await admin.post(
            "/api/admin/catalog",
            json={
                "content_type": "software",
                "slug": "cloudsite",
                "title": "CloudSite",
                "summary": "Catalog integration",
            },
        )
        assert created.status_code == 201, created.text
        entry_id = created.json()["entry_id"]
        assert created.json()["revision"] == 1

        admin_listing = await admin.get("/api/admin/catalog/entries")
        assert admin_listing.status_code == 200, admin_listing.text
        assert admin_listing.json()["items"][0]["slug"] == "cloudsite"
        updated = await admin.patch(
            f"/api/admin/catalog/entries/{entry_id}",
            json={"expected_revision": 1, "summary": "Updated summary"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["revision"] == 2
        stale = await admin.patch(
            f"/api/admin/catalog/entries/{entry_id}",
            json={"expected_revision": 1, "title": "Stale overwrite"},
        )
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "CATALOG_REVISION_CONFLICT"

        async with state_factory() as state:
            from cloudsite.models import CatalogRelease

            release = await state.scalar(
                select(CatalogRelease).where(CatalogRelease.entry_id == entry_id)
            )
            assert release is not None
            asset = await create_catalog_asset(
                state,
                release_id=release.release_id,
                slug="windows-x64",
                display_name="CloudSite Windows x64",
                platform="windows",
                kind="archive",
                actor="admin",
            )
            await state.commit()

        bound = await admin.post(
            f"/api/admin/catalog/{entry_id}/locations",
            json={
                "asset_id": asset.asset.asset_id,
                "resource_id": "r_" + "b" * 32,
                "is_primary": True,
            },
        )
        assert bound.status_code == 201, bound.text
        assert bound.json()["available"] is True

        preview = await admin.post(f"/api/admin/catalog/{entry_id}/preview")
        assert preview.status_code == 200, preview.text
        assert preview.json()["previewable"] is True

        published = await admin.post(
            f"/api/admin/catalog/entries/{entry_id}/publish",
            json={"expected_revision": 2},
        )
        assert published.status_code == 200, published.text
        assert published.json()["status"] == "published"
        assert published.json()["revision"] == 3

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as reader:
        reader.cookies.set(USER_SESSION_COOKIE, user_token)
        listing = await reader.get("/api/catalog")
        assert listing.status_code == 200, listing.text
        assert [item["entry_id"] for item in listing.json()["items"]] == [entry_id]
        detail = await reader.get(f"/api/catalog/{entry_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["locations"][0]["asset_id"] == asset.asset.asset_id

        rich_listing = await reader.get("/api/catalog/entries")
        assert rich_listing.status_code == 200, rich_listing.text
        assert rich_listing.json()["items"][0]["availability"] == "available"
        rich_detail = await reader.get(f"/api/catalog/entries/{entry_id}")
        assert rich_detail.status_code == 200, rich_detail.text
        assert rich_detail.json()["releases"][0]["release_id"] == release.release_id
        release_detail = await reader.get(f"/api/catalog/releases/{release.release_id}")
        assert release_detail.status_code == 200, release_detail.text
        assert release_detail.json()["assets"][0]["asset_id"] == asset.asset.asset_id
        asset_detail = await reader.get(f"/api/catalog/assets/{asset.asset.asset_id}")
        assert asset_detail.status_code == 200, asset_detail.text
        assert asset_detail.json()["locations"][0]["resource_id"] == "r_" + "b" * 32
        assert asset_detail.json()["locations"][0]["download_url"].startswith("/d/")

    await state_engine.dispose()
    await index_engine.dispose()


async def test_public_detail_hides_draft(monkeypatch):
    state_engine, index_engine, _, user_token = await _setup(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as admin:
        admin.cookies.set(main.SESSION_COOKIE, main.create_session_token("admin"))
        created = await admin.post(
            "/api/admin/catalog",
            json={"content_type": "software", "slug": "draft", "title": "Draft"},
        )
        entry_id = created.json()["entry_id"]
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as reader:
        reader.cookies.set(USER_SESSION_COOKIE, user_token)
        response = await reader.get(f"/api/catalog/{entry_id}")
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "CATALOG_ENTRY_NOT_FOUND"
        rich_response = await reader.get(f"/api/catalog/entries/{entry_id}")
        assert rich_response.status_code == 404
    await state_engine.dispose()
    await index_engine.dispose()


async def test_admin_catalog_rejects_anonymous(monkeypatch):
    state_engine, index_engine, _, _ = await _setup(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/admin/catalog")
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "ADMIN_REQUIRED"
    await state_engine.dispose()
    await index_engine.dispose()
