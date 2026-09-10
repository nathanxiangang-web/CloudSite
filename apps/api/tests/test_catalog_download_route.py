"""C2 下载签发端点端到端测试。

覆盖 POST /api/catalog/entries/{entry_id}/assets/{asset_id}/download：
- entry 未发布 → 404
- release 未发布 → 404
- asset 禁用 → 409 带 reason
- 无有效 location → 409
- 正常 → 302 且 Location 指向允许位置
- 审计记录实际 file_id（download_events source='catalog'）
- 不接受客户端传入镜像 URL
"""
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import auth, main
from cloudsite.database import IndexBase, StateBase
from cloudsite.download import DownloadResolution
from cloudsite.download_rate_limit import DownloadRateDecision
from cloudsite.models import (
    CatalogRelease,
    ContentRootMapping,
    DownloadEvent,
    Resource,
    SiteSettings,
    SystemSetting,
    User,
    utcnow,
)
from cloudsite.services.catalog import create_catalog_asset
from cloudsite.sessions import USER_SESSION_COOKIE, create_user_session

_RESOURCE_ID = "r_" + "b" * 32
_ALLOWED_DOWNLOAD_URL = "https://download.cloudsite.example/software/cloudsite-x64.zip"


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
    return state_engine, index_engine, state_factory, user_token


def _allow_download(monkeypatch, url=_ALLOWED_DOWNLOAD_URL):
    async def _fake_resolve(resource, connection):
        return DownloadResolution(url=url, target_host="download.cloudsite.example", base_path="/software", has_sign=True, steps=[])

    async def _fake_rate(address, now=None):
        return DownloadRateDecision(allowed=True)

    monkeypatch.setattr("cloudsite.routers.catalog.resolve_download_entry", _fake_resolve)
    monkeypatch.setattr("cloudsite.routers.catalog.check_download_rate", _fake_rate)


async def _make_published_entry_with_asset(monkeypatch):
    state_engine, index_engine, state_factory, user_token = await _setup(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as admin:
        admin.cookies.set(main.SESSION_COOKIE, main.create_session_token("admin"))
        created = await admin.post(
            "/api/admin/catalog/entries",
            json={"content_type": "software", "slug": "cloudsite", "title": "CloudSite"},
        )
        assert created.status_code == 201, created.text
        entry_id = created.json()["entry_id"]

        async with state_factory() as state:
            release = await state.scalar(
                select(CatalogRelease).where(CatalogRelease.entry_id == entry_id)
            )
            release_id = release.release_id
            asset_result = await create_catalog_asset(
                state,
                release_id=release_id,
                slug="windows-x64",
                display_name="CloudSite Windows x64",
                platform="windows",
                kind="archive",
                architecture="x64",
                actor="admin",
            )
            asset_id = asset_result.asset.asset_id
            await state.commit()

        bound = await admin.post(
            f"/api/admin/catalog/{entry_id}/locations",
            json={"asset_id": asset_id, "resource_id": _RESOURCE_ID, "is_primary": True},
        )
        assert bound.status_code == 201, bound.text
        location_id = bound.json()["location_id"]

        published = await admin.post(
            f"/api/admin/catalog/entries/{entry_id}/publish",
            json={"expected_revision": 1},
        )
        assert published.status_code == 200, published.text

    return {
        "state_engine": state_engine,
        "index_engine": index_engine,
        "state_factory": state_factory,
        "user_token": user_token,
        "entry_id": entry_id,
        "release_id": release_id,
        "asset_id": asset_id,
        "location_id": location_id,
        "resource_id": _RESOURCE_ID,
    }


def _reader_client(transport, user_token):
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    client.cookies.set(USER_SESSION_COOKIE, user_token)
    return client


async def test_download_entry_not_published_returns_404(monkeypatch):
    ctx = await _make_published_entry_with_asset(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    async with ctx["state_factory"]() as state:
        from cloudsite.models import CatalogEntry

        entry = await state.get(CatalogEntry, ctx["entry_id"])
        entry.status = "draft"
        await state.commit()
    try:
        async with _reader_client(transport, ctx["user_token"]) as reader:
            resp = await reader.post(
                f"/api/catalog/entries/{ctx['entry_id']}/assets/{ctx['asset_id']}/download"
            )
            assert resp.status_code == 404, resp.text
            assert resp.json()["detail"]["code"] == "CATALOG_ASSET_NOT_FOUND"
    finally:
        await ctx["state_engine"].dispose()
        await ctx["index_engine"].dispose()


async def test_download_release_not_published_returns_404(monkeypatch):
    ctx = await _make_published_entry_with_asset(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    async with ctx["state_factory"]() as state:
        draft_release = CatalogRelease(
            release_id="cr_" + "c" * 32,
            entry_id=ctx["entry_id"],
            slug="beta",
            title="Beta",
            status="draft",
            channel="beta",
        )
        state.add(draft_release)
        await state.flush()
        draft_asset = await create_catalog_asset(
            state,
            release_id=draft_release.release_id,
            slug="beta-x64",
            display_name="Beta x64",
            platform="windows",
            kind="archive",
            actor="admin",
        )
        draft_asset_id = draft_asset.asset.asset_id
        await state.commit()
    try:
        async with _reader_client(transport, ctx["user_token"]) as reader:
            resp = await reader.post(
                f"/api/catalog/entries/{ctx['entry_id']}/assets/{draft_asset_id}/download"
            )
            assert resp.status_code == 404, resp.text
            assert resp.json()["detail"]["code"] == "CATALOG_ASSET_NOT_FOUND"
    finally:
        await ctx["state_engine"].dispose()
        await ctx["index_engine"].dispose()


async def test_download_asset_disabled_returns_409_with_reason(monkeypatch):
    ctx = await _make_published_entry_with_asset(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    async with ctx["state_factory"]() as state:
        from cloudsite.models import CatalogAsset

        asset = await state.get(CatalogAsset, ctx["asset_id"])
        asset.status = "disabled"
        await state.commit()
    try:
        async with _reader_client(transport, ctx["user_token"]) as reader:
            resp = await reader.post(
                f"/api/catalog/entries/{ctx['entry_id']}/assets/{ctx['asset_id']}/download"
            )
            assert resp.status_code == 409, resp.text
            body = resp.json()["detail"]
            assert body["code"] == "CATALOG_ASSET_NOT_DOWNLOADABLE"
            assert body["reason"] == "asset_disabled"
    finally:
        await ctx["state_engine"].dispose()
        await ctx["index_engine"].dispose()


async def test_download_no_available_location_returns_409(monkeypatch):
    ctx = await _make_published_entry_with_asset(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    async with ctx["state_factory"]() as state:
        orphan_asset = await create_catalog_asset(
            state,
            release_id=ctx["release_id"],
            slug="orphan",
            display_name="Orphan asset",
            platform="linux",
            kind="archive",
            actor="admin",
        )
        orphan_asset_id = orphan_asset.asset.asset_id
        await state.commit()
    try:
        async with _reader_client(transport, ctx["user_token"]) as reader:
            resp = await reader.post(
                f"/api/catalog/entries/{ctx['entry_id']}/assets/{orphan_asset_id}/download"
            )
            assert resp.status_code == 409, resp.text
            body = resp.json()["detail"]
            assert body["code"] == "CATALOG_ASSET_NOT_DOWNLOADABLE"
            assert body["reason"] == "no_enabled_location"
    finally:
        await ctx["state_engine"].dispose()
        await ctx["index_engine"].dispose()


async def test_download_success_returns_302_to_allowed_location(monkeypatch):
    ctx = await _make_published_entry_with_asset(monkeypatch)
    _allow_download(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with _reader_client(transport, ctx["user_token"]) as reader:
            resp = await reader.post(
                f"/api/catalog/entries/{ctx['entry_id']}/assets/{ctx['asset_id']}/download"
            )
            assert resp.status_code == 302, resp.text
            assert resp.headers["location"] == _ALLOWED_DOWNLOAD_URL
    finally:
        await ctx["state_engine"].dispose()
        await ctx["index_engine"].dispose()


async def test_download_audit_records_file_id(monkeypatch):
    ctx = await _make_published_entry_with_asset(monkeypatch)
    _allow_download(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with _reader_client(transport, ctx["user_token"]) as reader:
            resp = await reader.post(
                f"/api/catalog/entries/{ctx['entry_id']}/assets/{ctx['asset_id']}/download"
            )
            assert resp.status_code == 302, resp.text

        async with ctx["state_factory"]() as state:
            events = list(
                (
                    await state.scalars(
                        select(DownloadEvent)
                        .where(DownloadEvent.source == "catalog")
                        .order_by(DownloadEvent.id.desc())
                    )
                ).all()
            )
            assert events, "expected at least one catalog download event"
            latest = events[0]
            assert latest.result == "success"
            assert latest.resource_id == ctx["resource_id"]
    finally:
        await ctx["state_engine"].dispose()
        await ctx["index_engine"].dispose()


async def test_download_ignores_client_mirror_url(monkeypatch):
    ctx = await _make_published_entry_with_asset(monkeypatch)
    _allow_download(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    evil_url = "https://evil.example/mirror/cloudsite-x64.zip"
    try:
        async with _reader_client(transport, ctx["user_token"]) as reader:
            resp = await reader.post(
                f"/api/catalog/entries/{ctx['entry_id']}/assets/{ctx['asset_id']}/download",
                json={"mirror_url": evil_url, "url": evil_url, "upstream_url": evil_url},
            )
            assert resp.status_code == 302, resp.text
            assert resp.headers["location"] == _ALLOWED_DOWNLOAD_URL
            assert evil_url not in resp.headers["location"]
    finally:
        await ctx["state_engine"].dispose()
        await ctx["index_engine"].dispose()
