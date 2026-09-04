import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import auth, main, site, userdata
from cloudsite.database import IndexBase, StateBase
from cloudsite.models import ContentRootMapping, Resource, SiteSettings, User, utcnow
from cloudsite.sessions import USER_SESSION_COOKIE, create_user_session


async def _store(monkeypatch):
    state_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    index_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    index_factory = async_sessionmaker(index_engine, expire_on_commit=False)
    async with state_engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as connection:
        await connection.run_sync(IndexBase.metadata.create_all)
    for mod in (main, auth, userdata, site):
        monkeypatch.setattr(mod, "StateSession", state_factory)
    for mod in (main, userdata):
        monkeypatch.setattr(mod, "IndexSession", index_factory)

    async with state_factory() as state:
        state.add(ContentRootMapping(id=1, content_type="file", display_name="文件", alist_path="/", enabled=True))
        state.add(SiteSettings(id=1, site_name="CloudSite", registration_enabled=True))
        owner = User(username="owner", username_normalized="owner", password_hash="x", status="active", created_at=utcnow(), updated_at=utcnow())
        other = User(username="other", username_normalized="other", password_hash="x", status="active", created_at=utcnow(), updated_at=utcnow())
        state.add_all([owner, other])
        await state.flush()
        _, owner_token = await create_user_session(state, owner.id, utcnow())
        _, other_token = await create_user_session(state, other.id, utcnow())
        await state.commit()

    async with index_factory() as index:
        index.add_all(
            [
                Resource(id="r-a", name="a.zip", path="/a.zip", parent_id=None, content_type="software", root_mapping_id=1, extension="zip", mime_type="application/zip", size=1, thumbnail="", status="active"),
                Resource(id="r-b", name="b.mp4", path="/b.mp4", parent_id=None, content_type="video", root_mapping_id=1, extension="mp4", mime_type="video/mp4", size=2, thumbnail="", status="active"),
            ]
        )
        await index.commit()

    return state_engine, index_engine, owner_token, other_token


async def _client():
    transport = httpx.ASGITransport(app=main.app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


async def test_favorite_add_is_idempotent_and_owned(monkeypatch):
    state_engine, index_engine, owner_token, other_token = await _store(monkeypatch)
    async with await _client() as client:
        first = await client.post("/api/me/favorites/r-a", cookies={USER_SESSION_COOKIE: owner_token})
        assert first.status_code == 201
        second = await client.post("/api/me/favorites/r-a", cookies={USER_SESSION_COOKIE: owner_token})
        assert second.status_code == 201

        owner_list = await client.get("/api/me/favorites", cookies={USER_SESSION_COOKIE: owner_token})
        assert [item["id"] for item in owner_list.json()["items"]] == ["r-a"]
        status = await client.get("/api/me/favorites/r-a", cookies={USER_SESSION_COOKIE: owner_token})
        assert status.json() == {"favorited": True}
        other_list = await client.get("/api/me/favorites", cookies={USER_SESSION_COOKIE: other_token})
        assert other_list.json()["items"] == []

        removed = await client.delete("/api/me/favorites/r-a", cookies={USER_SESSION_COOKIE: owner_token})
        assert removed.status_code == 200
        assert (await client.get("/api/me/favorites", cookies={USER_SESSION_COOKIE: owner_token})).json()["items"] == []
    await state_engine.dispose()
    await index_engine.dispose()


async def test_favorite_rejects_missing_or_disabled_resource(monkeypatch):
    state_engine, index_engine, owner_token, _ = await _store(monkeypatch)
    async with await _client() as client:
        missing = await client.post("/api/me/favorites/r-nope", cookies={USER_SESSION_COOKIE: owner_token})
        assert missing.status_code == 404
    await state_engine.dispose()
    await index_engine.dispose()


async def test_history_touch_throttle_and_clear(monkeypatch):
    state_engine, index_engine, owner_token, _ = await _store(monkeypatch)
    async with await _client() as client:
        await client.post("/api/me/history/r-a/touch", cookies={USER_SESSION_COOKIE: owner_token})
        await client.post("/api/me/history/r-a/touch", cookies={USER_SESSION_COOKIE: owner_token})
        await client.post("/api/me/history/r-b/touch", cookies={USER_SESSION_COOKIE: owner_token})

        history = (await client.get("/api/me/history", cookies={USER_SESSION_COOKIE: owner_token})).json()
        assert len(history["items"]) == 2
        a_row = next(item for item in history["items"] if item["id"] == "r-a")
        assert a_row["view_count"] == 1  # 5 分钟内只 Touch 一次

        await client.delete("/api/me/history/r-a", cookies={USER_SESSION_COOKIE: owner_token})
        assert len((await client.get("/api/me/history", cookies={USER_SESSION_COOKIE: owner_token})).json()["items"]) == 1

        await client.delete("/api/me/history", cookies={USER_SESSION_COOKIE: owner_token})
        assert (await client.get("/api/me/history", cookies={USER_SESSION_COOKIE: owner_token})).json()["items"] == []
    await state_engine.dispose()
    await index_engine.dispose()


async def test_history_and_lists_respect_publication_scope(monkeypatch):
    state_engine, index_engine, owner_token, _ = await _store(monkeypatch)
    async with await _client() as client:
        touched = await client.post("/api/me/history/r-a/touch", cookies={USER_SESSION_COOKIE: owner_token})
        assert touched.status_code == 204
        async with userdata.StateSession() as state:
            root = await state.get(ContentRootMapping, 1)
            root.enabled = False
            await state.commit()
        rejected = await client.post("/api/me/history/r-b/touch", cookies={USER_SESSION_COOKIE: owner_token})
        assert rejected.status_code == 404
        history = await client.get("/api/me/history", cookies={USER_SESSION_COOKIE: owner_token})
        assert history.json()["items"] == []
        assert history.json()["unavailable_count"] == 1
    await state_engine.dispose()
    await index_engine.dispose()


async def test_playback_save_resume_complete_and_reset(monkeypatch):
    state_engine, index_engine, owner_token, _ = await _store(monkeypatch)
    async with await _client() as client:
        saved = await client.put(
            "/api/me/playback/r-b",
            cookies={USER_SESSION_COOKIE: owner_token},
            json={"position_seconds": 1930, "duration_seconds": 7200},
        )
        assert saved.status_code == 200
        assert saved.json()["completed"] is False

        progress = (await client.get("/api/me/playback/r-b", cookies={USER_SESSION_COOKIE: owner_token})).json()
        assert progress["position_seconds"] == 1930

        # 完播：90% 比例
        done = await client.put(
            "/api/me/playback/r-b",
            cookies={USER_SESSION_COOKIE: owner_token},
            json={"position_seconds": 7000, "duration_seconds": 7200},
        )
        assert done.json()["completed"] is True

        await client.delete("/api/me/playback/r-b", cookies={USER_SESSION_COOKIE: owner_token})
        reset = (await client.get("/api/me/playback/r-b", cookies={USER_SESSION_COOKIE: owner_token})).json()
        assert reset["position_seconds"] == 0
    await state_engine.dispose()
    await index_engine.dispose()


async def test_playback_uses_last_write_wins_and_lists_incomplete_items(monkeypatch):
    state_engine, index_engine, owner_token, _ = await _store(monkeypatch)
    async with await _client() as client:
        await client.put("/api/me/playback/r-b", cookies={USER_SESSION_COOKIE: owner_token}, json={"position_seconds": 3600, "duration_seconds": 7200})
        # 0.5.1 允许“从头播放”写回较小进度，不再维护冲突协议。
        await client.put("/api/me/playback/r-b", cookies={USER_SESSION_COOKIE: owner_token}, json={"position_seconds": 300, "duration_seconds": 7200})
        progress = (await client.get("/api/me/playback/r-b", cookies={USER_SESSION_COOKIE: owner_token})).json()
        assert progress["position_seconds"] == 300
        listing = (await client.get("/api/me/playback", cookies={USER_SESSION_COOKIE: owner_token})).json()
        assert [item["id"] for item in listing["items"]] == ["r-b"]
    await state_engine.dispose()
    await index_engine.dispose()


async def test_short_video_is_not_completed_at_eighty_percent():
    assert userdata._compute_completed(80, 100) is False
    assert userdata._compute_completed(90, 100) is True


async def test_registration_disabled_rejects_register(monkeypatch):
    state_engine, index_engine, owner_token, _ = await _store(monkeypatch)
    async with auth.StateSession() as state:
        row = await state.get(SiteSettings, 1)
        row.registration_enabled = False
        await state.commit()
    async with await _client() as client:
        resp = await client.post(
            "/api/auth/register",
            json={"username": "newuser", "password": "password123", "password_confirm": "password123"},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "REGISTRATION_DISABLED"
    await state_engine.dispose()
    await index_engine.dispose()


async def test_public_site_settings_do_not_require_login(monkeypatch):
    state_engine, index_engine, _, _ = await _store(monkeypatch)
    async with await _client() as client:
        response = await client.get("/api/site")
        assert response.status_code == 200
        assert response.json()["site_name"] == "CloudSite"
        assert response.json()["registration_enabled"] is True
    await state_engine.dispose()
    await index_engine.dispose()
