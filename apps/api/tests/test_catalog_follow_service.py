"""C4 资源关注与更新通知应用层最小自测。

覆盖：
- 关注/取关/状态查询/退订开关
- 我的关注列表（含最新发布版本摘要，过滤未发布条目）
- 仅允许关注已发布条目
- 发布 release 时通知关注者，按 (release_id, user_id) 去重幂等
- 普通更新（非 publish）不触发通知
- 退订用户不收到通知
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.database import IndexBase, StateBase
from cloudsite.models import (
    CatalogEntry,
    CatalogRelease,
    CatalogReleaseNotification,
    ContentRootMapping,
    Notification,
    Resource,
    User,
)
from cloudsite.modules.catalog.contracts.public import (
    create_catalog_asset,
    create_catalog_entry,
    create_catalog_release,
    publish_catalog_entry,
    update_catalog_release,
)
from cloudsite.services.catalog_follow import (
    CatalogEntryNotFollowable,
    follow_entry,
    get_follow_status,
    list_my_follows,
    notify_release_subscribers,
    set_subscription_notify,
    unfollow_entry,
)


async def _bootstrap(tmp_path):
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)

    sf = async_sessionmaker(state_engine, expire_on_commit=False)
    ix = async_sessionmaker(index_engine, expire_on_commit=False)

    async with sf() as state:
        state.add(ContentRootMapping(id=1, content_type="software", display_name="software", alist_path="/software", enabled=True))
        state.add(User(id=1, username="alice", username_normalized="alice", password_hash="x", status="active"))
        state.add(User(id=2, username="bob", username_normalized="bob", password_hash="x", status="active"))
        await state.commit()
    async with ix() as index:
        index.add(Resource(id="r_soft_1", name="app.zip", path="/software/app.zip", parent_id=None, content_type="software", root_mapping_id=1, extension="zip", mime_type="application/zip", size=100, status="active"))
        await index.commit()

    return state_engine, index_engine, sf, ix


async def _make_published_entry(sf, ix, slug="myapp"):
    """创建一个已发布条目（含可用 location），返回 entry。"""
    async with sf() as state, ix() as index:
        result = await create_catalog_entry(state, content_type="software", slug=slug, title=f"{slug} title")
        await state.commit()
        entry = result.entry
        release = result.release
        asset = await create_catalog_asset(state, release_id=release.release_id, slug="pkg", display_name="package")
        await state.commit()
        from cloudsite.modules.catalog.contracts.public import attach_catalog_location
        await attach_catalog_location(state, index, asset_id=asset.asset.asset_id, resource_id="r_soft_1", is_primary=True)
        await state.commit()
        await publish_catalog_entry(state, index, entry_id=entry.entry_id, expected_revision=entry.revision)
        await state.commit()
        return entry.entry_id, release.release_id


async def test_follow_unfollow_status(tmp_path):
    se, ie, sf, ix = await _bootstrap(tmp_path)
    entry_id, _ = await _make_published_entry(sf, ix)

    async with sf() as state:
        st = await get_follow_status(state, user_id=1, entry_id=entry_id)
        assert not st.favorited and not st.notify_enabled

        r = await follow_entry(state, user_id=1, entry_id=entry_id)
        await state.commit()
        assert r.favorited and r.notify_enabled

        st = await get_follow_status(state, user_id=1, entry_id=entry_id)
        assert st.favorited and st.notify_enabled

        r = await unfollow_entry(state, user_id=1, entry_id=entry_id)
        await state.commit()
        assert not r.favorited

        st = await get_follow_status(state, user_id=1, entry_id=entry_id)
        assert not st.favorited

    await se.dispose()
    await ie.dispose()


async def test_follow_is_idempotent(tmp_path):
    se, ie, sf, ix = await _bootstrap(tmp_path)
    entry_id, _ = await _make_published_entry(sf, ix)

    async with sf() as state:
        await follow_entry(state, user_id=1, entry_id=entry_id)
        await state.commit()
        await follow_entry(state, user_id=1, entry_id=entry_id)
        await state.commit()
        st = await get_follow_status(state, user_id=1, entry_id=entry_id)
        assert st.favorited and st.notify_enabled
        rows = list((await state.scalars(select(Notification))).all())
        assert len(rows) == 0
    await se.dispose()
    await ie.dispose()


async def test_unfollow_then_refollow_resubscribes(tmp_path):
    se, ie, sf, ix = await _bootstrap(tmp_path)
    entry_id, _ = await _make_published_entry(sf, ix)

    async with sf() as state:
        await follow_entry(state, user_id=1, entry_id=entry_id)
        await state.commit()
        await set_subscription_notify(state, user_id=1, entry_id=entry_id, notify_enabled=False)
        await state.commit()
        st = await get_follow_status(state, user_id=1, entry_id=entry_id)
        assert st.favorited and not st.notify_enabled

        await unfollow_entry(state, user_id=1, entry_id=entry_id)
        await state.commit()
        await follow_entry(state, user_id=1, entry_id=entry_id)
        await state.commit()
        st = await get_follow_status(state, user_id=1, entry_id=entry_id)
        assert st.favorited and st.notify_enabled
    await se.dispose()
    await ie.dispose()


async def test_cannot_follow_unpublished_entry(tmp_path):
    se, ie, sf, ix = await _bootstrap(tmp_path)
    async with sf() as state, ix() as index:
        result = await create_catalog_entry(state, content_type="software", slug="draft-app", title="draft")
        await state.commit()
        with __import__("pytest").raises(CatalogEntryNotFollowable):
            await follow_entry(state, user_id=1, entry_id=result.entry.entry_id)
    await se.dispose()
    await ie.dispose()


async def test_list_my_follows_with_latest_release(tmp_path):
    se, ie, sf, ix = await _bootstrap(tmp_path)
    entry_id, _ = await _make_published_entry(sf, ix, slug="listed-app")

    async with sf() as state:
        await follow_entry(state, user_id=1, entry_id=entry_id)
        await state.commit()
        result = await list_my_follows(state, user_id=1, page=1, page_size=20)
        assert result.total == 1
        assert result.items[0]["entry_id"] == entry_id
        assert result.items[0]["latest_release"] is not None
        assert result.items[0]["notify_enabled"] is True
    await se.dispose()
    await ie.dispose()


async def test_notify_release_subscribers_dedup(tmp_path):
    se, ie, sf, ix = await _bootstrap(tmp_path)
    entry_id, _ = await _make_published_entry(sf, ix, slug="notify-app")

    async with sf() as state:
        await follow_entry(state, user_id=1, entry_id=entry_id)
        await follow_entry(state, user_id=2, entry_id=entry_id)
        await state.commit()

        new_release = await create_catalog_release(state, entry_id=entry_id, slug="v2", title="v2", release_notes="second")
        new_release.release.status = "published"
        new_release.release.published_at = __import__("cloudsite.models", fromlist=["utcnow"]).utcnow()
        await state.commit()
        entry = await state.get(CatalogEntry, entry_id)
        n1 = await notify_release_subscribers(state, release=new_release.release, entry=entry)
        assert n1 == 2

        n2 = await notify_release_subscribers(state, release=new_release.release, entry=entry)
        assert n2 == 0

        notifs = list((await state.scalars(select(Notification))).all())
        assert len(notifs) == 2
        dedup = list((await state.scalars(select(CatalogReleaseNotification))).all())
        assert len(dedup) == 2
    await se.dispose()
    await ie.dispose()


async def test_update_release_publish_triggers_notify(tmp_path):
    se, ie, sf, ix = await _bootstrap(tmp_path)
    entry_id, _ = await _make_published_entry(sf, ix, slug="trigger-app")

    async with sf() as state:
        await follow_entry(state, user_id=1, entry_id=entry_id)
        await state.commit()

        new_release = await create_catalog_release(state, entry_id=entry_id, slug="v2", title="v2")
        await state.commit()

        updated = await update_catalog_release(state, new_release.release.release_id, status="published", actor="admin")
        await state.commit()
        assert updated.status == "published"

        notifs = list((await state.scalars(select(Notification).where(Notification.user_id == 1))).all())
        assert len(notifs) == 1
        assert "v2" in notifs[0].title
    await se.dispose()
    await ie.dispose()


async def test_update_release_non_publish_does_not_notify(tmp_path):
    se, ie, sf, ix = await _bootstrap(tmp_path)
    entry_id, _ = await _make_published_entry(sf, ix, slug="silent-app")

    async with sf() as state:
        await follow_entry(state, user_id=1, entry_id=entry_id)
        await state.commit()
        new_release = await create_catalog_release(state, entry_id=entry_id, slug="v2", title="v2")
        await state.commit()

        await update_catalog_release(state, new_release.release.release_id, title="v2-renamed", actor="admin")
        await state.commit()
        notifs = list((await state.scalars(select(Notification))).all())
        assert len(notifs) == 0
    await se.dispose()
    await ie.dispose()


async def test_unsubscribed_user_not_notified(tmp_path):
    se, ie, sf, ix = await _bootstrap(tmp_path)
    entry_id, _ = await _make_published_entry(sf, ix, slug="optout-app")

    async with sf() as state:
        await follow_entry(state, user_id=1, entry_id=entry_id)
        await follow_entry(state, user_id=2, entry_id=entry_id)
        await state.commit()
        await set_subscription_notify(state, user_id=2, entry_id=entry_id, notify_enabled=False)
        await state.commit()

        new_release = await create_catalog_release(state, entry_id=entry_id, slug="v2", title="v2")
        new_release.release.status = "published"
        new_release.release.published_at = __import__("cloudsite.models", fromlist=["utcnow"]).utcnow()
        await state.commit()
        entry = await state.get(CatalogEntry, entry_id)
        n = await notify_release_subscribers(state, release=new_release.release, entry=entry)
        assert n == 1
        notifs = list((await state.scalars(select(Notification))).all())
        assert all(nt.user_id == 1 for nt in notifs)
    await se.dispose()
    await ie.dispose()
