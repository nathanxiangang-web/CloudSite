"""1.0 IDOR（Insecure Direct Object Reference）测试。

验证用户 A 不能访问/修改用户 B 的：
- favorites（收藏）
- history（浏览历史）
- playback（播放进度）
- shares（我的分享）

对应 1.0 开发文档第 30、31 节：Auth Bypass + Share Bypass。
"""
import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import auth, main, userdata
from cloudsite.database import IndexBase, StateBase
from cloudsite.models import ContentRootMapping, Resource, User, utcnow
from cloudsite.sessions import USER_SESSION_COOKIE, create_user_session


async def _idor_store(monkeypatch):
    """创建两个用户和共享资源的测试环境。"""
    state_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    index_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    index_factory = async_sessionmaker(index_engine, expire_on_commit=False)
    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)
    for mod in (main, auth, userdata):
        if hasattr(mod, "StateSession"):
            monkeypatch.setattr(mod, "StateSession", state_factory)
        if hasattr(mod, "IndexSession"):
            monkeypatch.setattr(mod, "IndexSession", index_factory)

    async with state_factory() as state:
        state.add(ContentRootMapping(id=1, content_type="file", display_name="文件", alist_path="/", enabled=True))
        users = [
            User(username="alice", username_normalized="alice", password_hash="x", status="active", created_at=utcnow(), updated_at=utcnow()),
            User(username="bob", username_normalized="bob", password_hash="x", status="active", created_at=utcnow(), updated_at=utcnow()),
        ]
        state.add_all(users)
        await state.flush()
        _, alice_token = await create_user_session(state, users[0].id, utcnow())
        _, bob_token = await create_user_session(state, users[1].id, utcnow())
        await state.commit()
        alice_id = users[0].id
        bob_id = users[1].id

    async with index_factory() as index:
        index.add(Resource(id="r_shared", name="shared.zip", path="/shared.zip", parent_id=None, content_type="software", root_mapping_id=1, extension="zip", mime_type="application/zip", size=100, thumbnail="", status="active"))
        await index.commit()

    return state_engine, index_engine, alice_id, alice_token, bob_id, bob_token


async def test_favorites_are_user_isolated(monkeypatch):
    """用户 A 的收藏列表不包含用户 B 的收藏，且 B 不能删除 A 的收藏。"""
    state_engine, index_engine, _, alice_token, _, bob_token = await _idor_store(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Alice 添加收藏
        add = await client.post("/api/me/favorites/r_shared", cookies={USER_SESSION_COOKIE: alice_token})
        assert add.status_code == 201

        # Alice 能看到收藏
        alice_favs = await client.get("/api/me/favorites", cookies={USER_SESSION_COOKIE: alice_token})
        assert alice_favs.status_code == 200
        assert len(alice_favs.json().get("items", [])) == 1

        # Bob 看不到 Alice 的收藏
        bob_favs = await client.get("/api/me/favorites", cookies={USER_SESSION_COOKIE: bob_token})
        assert bob_favs.status_code == 200
        assert len(bob_favs.json().get("items", [])) == 0

        # Bob 可以添加同一个资源的收藏（各自独立）
        bob_add = await client.post("/api/me/favorites/r_shared", cookies={USER_SESSION_COOKIE: bob_token})
        assert bob_add.status_code == 201

        # Bob 删除收藏不影响 Alice
        bob_del = await client.delete("/api/me/favorites/r_shared", cookies={USER_SESSION_COOKIE: bob_token})
        assert bob_del.status_code == 200

        alice_favs2 = await client.get("/api/me/favorites", cookies={USER_SESSION_COOKIE: alice_token})
        assert len(alice_favs2.json().get("items", [])) == 1

    await state_engine.dispose()
    await index_engine.dispose()


async def test_history_is_user_isolated(monkeypatch):
    """用户 A 的浏览历史不包含用户 B 的历史。"""
    state_engine, index_engine, _, alice_token, _, bob_token = await _idor_store(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Alice 记录浏览历史
        await client.post("/api/me/history/r_shared/touch", cookies={USER_SESSION_COOKIE: alice_token})

        # Alice 能看到历史
        alice_hist = await client.get("/api/me/history", cookies={USER_SESSION_COOKIE: alice_token})
        assert len(alice_hist.json().get("items", [])) == 1

        # Bob 看不到 Alice 的历史
        bob_hist = await client.get("/api/me/history", cookies={USER_SESSION_COOKIE: bob_token})
        assert len(bob_hist.json().get("items", [])) == 0

    await state_engine.dispose()
    await index_engine.dispose()


async def test_playback_is_user_isolated(monkeypatch):
    """用户 A 的播放进度不包含用户 B 的进度。"""
    state_engine, index_engine, _, alice_token, _, bob_token = await _idor_store(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Alice 保存播放进度
        save = await client.put("/api/me/playback/r_shared", cookies={USER_SESSION_COOKIE: alice_token}, json={"position_seconds": 60, "duration_seconds": 120})
        assert save.status_code == 200, f"save failed: {save.status_code} {save.text}"

        # Alice 能看到进度
        alice_pb = await client.get("/api/me/playback", cookies={USER_SESSION_COOKIE: alice_token})
        assert len(alice_pb.json().get("items", [])) == 1

        # Bob 看不到 Alice 的进度
        bob_pb = await client.get("/api/me/playback", cookies={USER_SESSION_COOKIE: bob_token})
        assert len(bob_pb.json().get("items", [])) == 0

        # Bob 不能读取 Alice 的特定资源进度（404 或空进度，不是 Alice 的 60s）
        bob_pb_detail = await client.get("/api/me/playback/r_shared", cookies={USER_SESSION_COOKIE: bob_token})
        if bob_pb_detail.status_code == 200:
            pb = bob_pb_detail.json()
            assert pb.get("position_seconds", 0) == 0, "Bob 不应看到 Alice 的播放进度"
        else:
            assert bob_pb_detail.status_code == 404

    await state_engine.dispose()
    await index_engine.dispose()


async def test_my_shares_are_user_isolated(monkeypatch):
    """用户 A 的分享列表不包含用户 B 的分享，且 B 不能修改/删除 A 的分享。"""
    state_engine, index_engine, _, alice_token, _, bob_token = await _idor_store(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Alice 创建分享
        created = await client.post(
            "/api/my/shares",
            cookies={USER_SESSION_COOKIE: alice_token},
            json={"object_type": "resource", "object_id": "r_shared", "access_mode": "code", "duration": "1h"},
        )
        assert created.status_code == 200
        token = created.json()["token"]

        # Alice 能看到分享
        alice_shares = await client.get("/api/my/shares", cookies={USER_SESSION_COOKIE: alice_token})
        assert len(alice_shares.json().get("items", [])) == 1

        # Bob 看不到 Alice 的分享
        bob_shares = await client.get("/api/my/shares", cookies={USER_SESSION_COOKIE: bob_token})
        assert len(bob_shares.json().get("items", [])) == 0

        # Bob 不能修改 Alice 的分享
        bob_modify = await client.patch(
            f"/api/my/shares/{token}",
            cookies={USER_SESSION_COOKIE: bob_token},
            json={"action": "cancel"},
        )
        assert bob_modify.status_code == 404

        # Bob 不能删除 Alice 的分享
        bob_delete = await client.delete(f"/api/my/shares/{token}", cookies={USER_SESSION_COOKIE: bob_token})
        assert bob_delete.status_code == 404

        # Alice 的分享仍然存在
        alice_shares2 = await client.get("/api/my/shares", cookies={USER_SESSION_COOKIE: alice_token})
        assert len(alice_shares2.json().get("items", [])) == 1

    await state_engine.dispose()
    await index_engine.dispose()
