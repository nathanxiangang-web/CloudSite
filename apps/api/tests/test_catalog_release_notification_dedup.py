"""C4 更新通知去重端到端测试：发布 release 通知订阅者、重复发布（unpublish→
publish）不重复通知、普通字段更新不触发通知、文件收藏与 catalog 关注语义分离。
"""
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import auth, main
from cloudsite.database import IndexBase, StateBase
from cloudsite.models import (
    CatalogReleaseNotification,
    ContentRootMapping,
    Notification,
    Resource,
    SiteSettings,
    SystemSetting,
    User,
    UserFavorite,
    utcnow,
)
from cloudsite.services.catalog import (
    attach_catalog_location,
    create_catalog_asset,
    create_catalog_entry,
    create_catalog_release,
    publish_catalog_entry,
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
    from cloudsite import userdata
    monkeypatch.setattr(userdata, "StateSession", sf)
    monkeypatch.setattr(userdata, "IndexSession", ix)
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


def _admin_client(transport):
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    client.cookies.set(main.SESSION_COOKIE, main.create_session_token("admin"))
    return client


async def test_publish_release_notifies_subscribers(monkeypatch):
    se, ie, sf, ix, tokens = await _setup(monkeypatch)
    entry_id, _ = await _make_published_entry(sf, ix, slug="notify-app")
    transport = httpx.ASGITransport(app=main.app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(USER_SESSION_COOKIE, tokens["alice"])
        await client.post(f"/api/me/catalog/favorites/{entry_id}")
        client.cookies.set(USER_SESSION_COOKIE, tokens["bob"])
        await client.post(f"/api/me/catalog/favorites/{entry_id}")

    async with sf() as state:
        new_release = await create_catalog_release(state, entry_id=entry_id, slug="v2", title="v2", release_notes="second")
        await state.commit()
        new_release_id = new_release.release.release_id

    async with _admin_client(transport) as admin:
        resp = await admin.patch(f"/api/admin/catalog/releases/{new_release_id}", json={"status": "published"})
        assert resp.status_code == 200, resp.text

    async with sf() as state:
        notifs = list((await state.scalars(select(Notification))).all())
        assert len(notifs) == 2
        dedup = list((await state.scalars(select(CatalogReleaseNotification))).all())
        assert len(dedup) == 2
        assert all("v2" in n.title for n in notifs)
    await se.dispose()
    await ie.dispose()


async def test_republish_does_not_duplicate_notification(monkeypatch):
    se, ie, sf, ix, tokens = await _setup(monkeypatch)
    entry_id, _ = await _make_published_entry(sf, ix, slug="dedup-app")
    transport = httpx.ASGITransport(app=main.app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(USER_SESSION_COOKIE, tokens["alice"])
        await client.post(f"/api/me/catalog/favorites/{entry_id}")

    async with sf() as state:
        new_release = await create_catalog_release(state, entry_id=entry_id, slug="v2", title="v2")
        await state.commit()
        new_release_id = new_release.release.release_id

    async with _admin_client(transport) as admin:
        first = await admin.patch(f"/api/admin/catalog/releases/{new_release_id}", json={"status": "published"})
        assert first.status_code == 200, first.text
        await admin.patch(f"/api/admin/catalog/releases/{new_release_id}", json={"status": "draft"})
        second = await admin.patch(f"/api/admin/catalog/releases/{new_release_id}", json={"status": "published"})
        assert second.status_code == 200, second.text

    async with sf() as state:
        alice = await state.scalar(select(User.id).where(User.username_normalized == "alice"))
        notifs = list((await state.scalars(select(Notification).where(Notification.user_id == alice))).all())
        assert len(notifs) == 1
        dedup = list((await state.scalars(select(CatalogReleaseNotification).where(CatalogReleaseNotification.user_id == alice))).all())
        assert len(dedup) == 1
    await se.dispose()
    await ie.dispose()


async def test_non_publish_field_update_does_not_notify(monkeypatch):
    se, ie, sf, ix, tokens = await _setup(monkeypatch)
    entry_id, _ = await _make_published_entry(sf, ix, slug="silent-app")
    transport = httpx.ASGITransport(app=main.app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(USER_SESSION_COOKIE, tokens["alice"])
        await client.post(f"/api/me/catalog/favorites/{entry_id}")

    async with sf() as state:
        new_release = await create_catalog_release(state, entry_id=entry_id, slug="v2", title="v2")
        await state.commit()
        new_release_id = new_release.release.release_id

    async with _admin_client(transport) as admin:
        resp = await admin.patch(f"/api/admin/catalog/releases/{new_release_id}", json={"title": "v2-renamed", "release_notes": "updated notes"})
        assert resp.status_code == 200, resp.text

    async with sf() as state:
        notifs = list((await state.scalars(select(Notification))).all())
        assert len(notifs) == 0
        dedup = list((await state.scalars(select(CatalogReleaseNotification))).all())
        assert len(dedup) == 0
    await se.dispose()
    await ie.dispose()


async def test_user_favorite_does_not_trigger_catalog_notification(monkeypatch):
    """文件收藏（UserFavorite 指向 resource_id）不应被重解释为 catalog 关注：
    发布 release 时 UserFavorite 用户不收到 CatalogReleaseNotification。
    """
    se, ie, sf, ix, tokens = await _setup(monkeypatch)
    entry_id, _ = await _make_published_entry(sf, ix, slug="fav-isolation-app")

    async with sf() as state:
        alice = await state.scalar(select(User.id).where(User.username_normalized == "alice"))
        state.add(UserFavorite(user_id=alice, resource_id=RESOURCE_ID))
        await state.commit()
        new_release = await create_catalog_release(state, entry_id=entry_id, slug="v2", title="v2")
        new_release.release.status = "published"
        new_release.release.published_at = utcnow()
        await state.commit()
        from cloudsite.models import CatalogEntry
        from cloudsite.services.catalog_follow import notify_release_subscribers
        entry = await state.get(CatalogEntry, entry_id)
        n = await notify_release_subscribers(state, release=new_release.release, entry=entry)
        assert n == 0

    async with sf() as state:
        alice = await state.scalar(select(User.id).where(User.username_normalized == "alice"))
        notifs = list((await state.scalars(select(Notification).where(Notification.user_id == alice))).all())
        assert len(notifs) == 0
        dedup = list((await state.scalars(select(CatalogReleaseNotification).where(CatalogReleaseNotification.user_id == alice))).all())
        assert len(dedup) == 0
    await se.dispose()
    await ie.dispose()


async def test_catalog_favorite_and_user_favorite_are_separate(monkeypatch):
    """CatalogFavorite（entry_id 维度）与 UserFavorite（resource_id 维度）分表：
    关注 catalog 条目不创建 UserFavorite，反之亦然。列表端点互不混入。
    """
    se, ie, sf, ix, tokens = await _setup(monkeypatch)
    entry_id, _ = await _make_published_entry(sf, ix, slug="separate-app")
    transport = httpx.ASGITransport(app=main.app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(USER_SESSION_COOKIE, tokens["alice"])
        await client.post(f"/api/me/catalog/favorites/{entry_id}")
        await client.post(f"/api/me/favorites/{RESOURCE_ID}")

    async with sf() as state:
        user_favs = list((await state.scalars(select(UserFavorite))).all())
        assert len(user_favs) == 1
        assert user_favs[0].resource_id == RESOURCE_ID
        from cloudsite.models import CatalogFavorite
        cat_favs = list((await state.scalars(select(CatalogFavorite))).all())
        assert len(cat_favs) == 1
        assert cat_favs[0].entry_id == entry_id

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(USER_SESSION_COOKIE, tokens["alice"])
        cat_listing = await client.get("/api/me/catalog/favorites")
        assert cat_listing.status_code == 200, cat_listing.text
        assert cat_listing.json()["total"] == 1
        assert cat_listing.json()["items"][0]["entry_id"] == entry_id
        file_listing = await client.get("/api/me/favorites")
        assert file_listing.status_code == 200, file_listing.text
        assert all(item["id"] == RESOURCE_ID for item in file_listing.json()["items"])
    await se.dispose()
    await ie.dispose()
