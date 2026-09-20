import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import auth, main
from cloudsite.database import IndexBase, StateBase
from cloudsite.models import ContentRootMapping, Resource, Share, User, utcnow
from cloudsite.sessions import USER_SESSION_COOKIE, create_user_session


async def user_share_store(monkeypatch):
    state_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    index_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    index_factory = async_sessionmaker(index_engine, expire_on_commit=False)
    async with state_engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as connection:
        await connection.run_sync(IndexBase.metadata.create_all)
    monkeypatch.setattr(main, "StateSession", state_factory)
    monkeypatch.setattr(auth, "StateSession", state_factory)
    monkeypatch.setattr(main, "IndexSession", index_factory)

    async with state_factory() as state:
        state.add(ContentRootMapping(id=1, content_type="file", display_name="文件", alist_path="/", enabled=True))
        users = [
            User(username="owner", username_normalized="owner", password_hash="not-used", status="active", created_at=utcnow(), updated_at=utcnow()),
            User(username="other", username_normalized="other", password_hash="not-used", status="active", created_at=utcnow(), updated_at=utcnow()),
        ]
        state.add_all(users)
        await state.flush()
        _, owner_token = await create_user_session(state, users[0].id, utcnow())
        _, other_token = await create_user_session(state, users[1].id, utcnow())
        await state.commit()
        owner_id = users[0].id

    async with index_factory() as index:
        index.add(Resource(id="r_user_share", name="user-share.zip", path="/user-share.zip", parent_id=None, content_type="software", root_mapping_id=1, extension="zip", mime_type="application/zip", size=1024, thumbnail="", status="active"))
        await index.commit()

    return state_engine, index_engine, state_factory, owner_id, owner_token, other_token


async def test_user_share_creation_is_owned_and_public_link_stays_anonymous(monkeypatch):
    state_engine, index_engine, state_factory, owner_id, owner_token, other_token = await user_share_store(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        anonymous = await client.post(
            "/api/my/shares",
            json={"object_type": "resource", "object_id": "r_user_share", "access_mode": "code", "duration": "1h"},
        )
        assert anonymous.status_code == 401

        created = await client.post(
            "/api/my/shares",
            cookies={USER_SESSION_COOKIE: owner_token},
            json={"object_type": "resource", "object_id": "r_user_share", "title": "用户分享", "access_mode": "code", "duration": "1h"},
        )
        assert created.status_code == 200
        payload = created.json()
        assert len(payload["code"]) == 4
        token = payload["token"]

        public_meta = await client.get(f"/api/public/shares/{token}")
        assert public_meta.status_code == 200
        assert public_meta.json()["status"] == "code_required"

        owner_list = await client.get("/api/my/shares", cookies={USER_SESSION_COOKIE: owner_token})
        assert [item["token"] for item in owner_list.json()["items"]] == [token]
        other_list = await client.get("/api/my/shares", cookies={USER_SESSION_COOKIE: other_token})
        assert other_list.json()["items"] == []

        denied = await client.patch(
            f"/api/my/shares/{token}",
            cookies={USER_SESSION_COOKIE: other_token},
            json={"action": "cancel"},
        )
        assert denied.status_code == 404

        removed = await client.delete(f"/api/my/shares/{token}", cookies={USER_SESSION_COOKIE: owner_token})
        assert removed.status_code == 200

    async with state_factory() as state:
        assert await state.get(Share, token) is None
        assert owner_id > 0
    await state_engine.dispose()
    await index_engine.dispose()


async def test_user_share_endpoint_rejects_non_resource_targets(monkeypatch):
    state_engine, index_engine, _, _, owner_token, _ = await user_share_store(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/my/shares",
            cookies={USER_SESSION_COOKIE: owner_token},
            json={"object_type": "folder", "object_id": "folder", "access_mode": "code", "duration": "1h"},
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "USER_SHARE_RESOURCE_ONLY"
    await state_engine.dispose()
    await index_engine.dispose()
