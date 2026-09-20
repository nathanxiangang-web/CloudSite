"""C4 资源关注路由端到端测试：通过真实 HTTP 边界验证 follow/unfollow/status/
subscription/list 路由的认证、可见性过滤、幂等与退订语义。
"""
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import auth, main
from cloudsite.database import IndexBase, StateBase
from cloudsite.models import (
    CatalogEntry,
    CatalogReleaseNotification,
    ContentRootMapping,
    Notification,
    Resource,
    SiteSettings,
    SystemSetting,
    User,
    utcnow,
)
from cloudsite.modules.catalog.contracts.public import (
    attach_catalog_location,
    create_catalog_asset,
    create_catalog_entry,
    create_catalog_release,
    publish_catalog_entry,
    update_catalog_release,
)
from cloudsite.sessions import USER_SESSION_COOKIE, create_user_session

RESOURCE_ID = "r_" + "b" * 32


async def _setup(monkeypatch):
    state_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    index_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)
    sf = async_sessionmaker(state_engine, expire_on_commit=False)
    ix = async_sessionmaker(index_engine, expire_on_commit=False)

    async with sf() as state:
        state.add_all([
            SiteSettings(id=1),
            SystemSetting(key="setup_completed", value="true", value_type="string"),
            ContentRootMapping(id=1, content_type="software", display_name="Software", alist_path="/software", enabled=True),
        ])
        tokens = {}
        for name in ("alice", "bob"):
            user = User(username=name, username_normalized=name, password_hash="x", status="active", created_at=utcnow(), updated_at=utcnow())
            state.add(user)
            await state.flush()
            _, token = await create_user_session(state, user.id, utcnow())
            tokens[name] = token
        await state.commit()
    async with ix() as index:
        index.add(Resource(id=RESOURCE_ID, name="cloudsite-x64.zip", path="/software/cloudsite-x64.zip", parent_id=None, content_type="software", root_mapping_id=1, extension="zip", mime_type="application/zip", size=123, status="active"))
        await index.commit()

    monkeypatch.setattr(main, "StateSession", sf)
    monkeypatch.setattr(main, "IndexSession", ix)
    monkeypatch.setattr(auth, "StateSession", sf)
    return state_engine, index_engine, sf, ix, tokens


async def _make_published_entry(sf, ix, slug="myapp"):
    async with sf() as state, ix() as index:
        result = await create_catalog_entry(state, content_type="software", slug=slug, title=f"{slug} title")
        await state.commit()
        entry = result.entry
        release = result.release
        asset = await create_catalog_asset(state, release_id=release.release_id, slug="pkg", display_name="package")
        await state.commit()
        await attach_catalog_location(state, index, asset_id=asset.asset.asset_id, resource_id=RESOURCE_ID, is_primary=True)
        await state.commit()
        await publish_catalog_entry(state, index, entry_id=entry.entry_id, expected_revision=entry.revision)
        await state.commit()
        return entry.entry_id, release.release_id


async def test_follow_endpoints_require_login(monkeypatch):
    se, ie, sf, ix, _ = await _setup(monkeypatch)
    entry_id, _ = await _make_published_entry(sf, ix)
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        for method in ("post", "delete", "get", "patch"):
            kwargs = {"json": {"notify_enabled": False}} if method == "patch" else {}
            resp = await getattr(client, method)(f"/api/me/catalog/favorites/{entry_id}", **kwargs)
            assert resp.status_code == 401, (method, resp.text)
            assert resp.json()["detail"]["code"] == "AUTH_REQUIRED"
    await se.dispose()
    await ie.dispose()


async def test_follow_unpublished_entry_rejected(monkeypatch):
    se, ie, sf, ix, tokens = await _setup(monkeypatch)
    async with sf() as state:
        result = await create_catalog_entry(state, content_type="software", slug="draft-app", title="draft")
        await state.commit()
        draft_entry_id = result.entry.entry_id

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(USER_SESSION_COOKIE, tokens["alice"])
        resp = await client.post(f"/api/me/catalog/favorites/{draft_entry_id}")
        assert resp.status_code == 404, resp.text
        assert resp.json()["detail"]["code"] == "CATALOG_ENTRY_NOT_FOUND"
    await se.dispose()
    await ie.dispose()


async def test_follow_is_idempotent_via_http(monkeypatch):
    se, ie, sf, ix, tokens = await _setup(monkeypatch)
    entry_id, _ = await _make_published_entry(sf, ix, slug="idem-app")
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(USER_SESSION_COOKIE, tokens["alice"])
        first = await client.post(f"/api/me/catalog/favorites/{entry_id}")
        assert first.status_code == 200, first.text
        assert first.json()["favorited"] is True
        second = await client.post(f"/api/me/catalog/favorites/{entry_id}")
        assert second.status_code == 200, second.text
        status = await client.get(f"/api/me/catalog/favorites/{entry_id}")
        assert status.json() == {"favorited": True, "notify_enabled": True}

    async with sf() as state:
        notifs = list((await state.scalars(select(Notification))).all())
        assert len(notifs) == 0
    await se.dispose()
    await ie.dispose()


async def test_unfollow_and_patch_subscription_via_http(monkeypatch):
    se, ie, sf, ix, tokens = await _setup(monkeypatch)
    entry_id, _ = await _make_published_entry(sf, ix, slug="sub-app")
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(USER_SESSION_COOKIE, tokens["alice"])
        await client.post(f"/api/me/catalog/favorites/{entry_id}")
        off = await client.patch(f"/api/me/catalog/favorites/{entry_id}", json={"notify_enabled": False})
        assert off.status_code == 200, off.text
        assert off.json() == {"ok": True, "favorited": True, "notify_enabled": False}
        status = await client.get(f"/api/me/catalog/favorites/{entry_id}")
        assert status.json()["notify_enabled"] is False
        removed = await client.delete(f"/api/me/catalog/favorites/{entry_id}")
        assert removed.json()["favorited"] is False
        status = await client.get(f"/api/me/catalog/favorites/{entry_id}")
        assert status.json() == {"favorited": False, "notify_enabled": False}
    await se.dispose()
    await ie.dispose()


async def test_follow_list_only_returns_published(monkeypatch):
    se, ie, sf, ix, tokens = await _setup(monkeypatch)
    entry_a, _ = await _make_published_entry(sf, ix, slug="list-a")
    entry_b, _ = await _make_published_entry(sf, ix, slug="list-b")
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(USER_SESSION_COOKIE, tokens["alice"])
        await client.post(f"/api/me/catalog/favorites/{entry_a}")
        await client.post(f"/api/me/catalog/favorites/{entry_b}")
        listing = await client.get("/api/me/catalog/favorites?page=1&page_size=20")
        assert listing.status_code == 200, listing.text
        body = listing.json()
        assert body["total"] == 2
        assert {item["entry_id"] for item in body["items"]} == {entry_a, entry_b}

    async with sf() as state:
        entry = await state.get(CatalogEntry, entry_b)
        entry.status = "disabled"
        entry.revision = entry.revision + 1
        await state.commit()

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(USER_SESSION_COOKIE, tokens["alice"])
        listing = await client.get("/api/me/catalog/favorites?page=1&page_size=20")
        body = listing.json()
        assert body["total"] == 1
        assert body["items"][0]["entry_id"] == entry_a
    await se.dispose()
    await ie.dispose()


async def test_unsubscribed_user_not_notified_on_new_release(monkeypatch):
    se, ie, sf, ix, tokens = await _setup(monkeypatch)
    entry_id, _ = await _make_published_entry(sf, ix, slug="optout-route-app")
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(USER_SESSION_COOKIE, tokens["alice"])
        await client.post(f"/api/me/catalog/favorites/{entry_id}")
        off = await client.patch(f"/api/me/catalog/favorites/{entry_id}", json={"notify_enabled": False})
        assert off.json()["notify_enabled"] is False

    async with sf() as state:
        new_release = await create_catalog_release(state, entry_id=entry_id, slug="v2", title="v2", release_notes="second")
        await state.commit()
        await update_catalog_release(state, new_release.release.release_id, status="published", actor="admin")
        await state.commit()

    async with sf() as state:
        alice = await state.scalar(select(User.id).where(User.username_normalized == "alice"))
        notifs = list((await state.scalars(select(Notification).where(Notification.user_id == alice))).all())
        assert len(notifs) == 0
        dedup = list((await state.scalars(select(CatalogReleaseNotification).where(CatalogReleaseNotification.user_id == alice))).all())
        assert len(dedup) == 0
    await se.dispose()
    await ie.dispose()


async def test_follow_list_pagination(monkeypatch):
    se, ie, sf, ix, tokens = await _setup(monkeypatch)
    created_ids = []
    for i in range(3):
        eid, _ = await _make_published_entry(sf, ix, slug=f"page-app-{i}")
        created_ids.append(eid)
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(USER_SESSION_COOKIE, tokens["alice"])
        for eid in created_ids:
            await client.post(f"/api/me/catalog/favorites/{eid}")
        first = await client.get("/api/me/catalog/favorites?page=1&page_size=2")
        body = first.json()
        assert body["total"] == 3
        assert body["page_size"] == 2
        assert len(body["items"]) == 2
        second = await client.get("/api/me/catalog/favorites?page=2&page_size=2")
        assert len(second.json()["items"]) == 1
    await se.dispose()
    await ie.dispose()
