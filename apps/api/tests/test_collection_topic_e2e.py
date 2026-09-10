"""D2 专题端到端测试：CollectionItem 强类型、专题字段读写、3 个种子专题可查询、移除条目后计数正确。"""
import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import auth, main
from cloudsite.database import IndexBase, StateBase
from cloudsite.models import (
    CatalogEntry,
    Collection,
    CollectionItem,
    ContentRootMapping,
    Resource,
    SystemSetting,
    User,
    utcnow,
)
from cloudsite.sessions import USER_SESSION_COOKIE, create_user_session
from cloudsite.services.collections import collection_dict
from cloudsite.services.collection_seeds import seed_default_collections


async def _bootstrap(tmp_path=None):
    url = f"sqlite+aiosqlite:///{tmp_path / 'state.db'}" if tmp_path else "sqlite+aiosqlite:///:memory:"
    state_engine = create_async_engine(url)
    index_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)
    state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    index_factory = async_sessionmaker(index_engine, expire_on_commit=False)
    return state_engine, index_engine, state_factory, index_factory


async def _seed_user(state_factory):
    async with state_factory() as state:
        state.add(SystemSetting(key="setup_completed", value="true", value_type="string"))
        user = User(username="reader", username_normalized="reader", password_hash="x", status="active", created_at=utcnow(), updated_at=utcnow())
        state.add(user)
        await state.flush()
        _, user_token = await create_user_session(state, user.id, utcnow())
        await state.commit()
    return user_token


def _patch_sessions(monkeypatch, state_factory, index_factory):
    monkeypatch.setattr(main, "StateSession", state_factory)
    monkeypatch.setattr(main, "IndexSession", index_factory)
    monkeypatch.setattr(auth, "StateSession", state_factory)


async def test_collection_item_strong_typing_resource_and_catalog_entry(tmp_path):
    """item_type='resource' 走 resource_id；'catalog_entry' 走 catalog_entry_id；NULL resource_id 不违反约束。"""
    state_engine, index_engine, state_factory, index_factory = await _bootstrap(tmp_path)
    async with state_factory() as state, index_factory() as index:
        state.add(ContentRootMapping(id=1, content_type="software", display_name="Public", alist_path="/public", enabled=True))
        state.add(Collection(id=100, name="Mixed Topic", description="", cover="", status="active", visible_on_home=True, sort_order=0))
        state.add(CollectionItem(id=1, collection_id=100, item_type="resource", resource_id="res-1", sort_order=0))
        state.add(CollectionItem(id=2, collection_id=100, item_type="catalog_entry", catalog_entry_id="ce-1", resource_id=None, sort_order=1))
        state.add(CollectionItem(id=3, collection_id=100, item_type="resource", resource_id=None, sort_order=2))
        state.add(CatalogEntry(entry_id="ce-1", content_type="software", slug="seed-entry", title="Seed Entry", summary="", status="published", revision=1))
        index.add(Resource(id="res-1", root_mapping_id=1, name="file.zip", path="/public/file.zip", content_type="software", status="active"))
        await state.commit()
        await index.commit()

        collection = await state.get(Collection, 100)
        payload = await collection_dict(state, index, collection, include_items=True)
        types = {item.get("item_type") for item in payload["items"]}
        assert types == {"resource", "catalog_entry"}
        assert payload["item_count"] == 2

        resource_item = next(item for item in payload["items"] if item["item_type"] == "resource")
        assert resource_item["id"] == "res-1"
        catalog_item = next(item for item in payload["items"] if item["item_type"] == "catalog_entry")
        assert catalog_item["catalog_entry_id"] == "ce-1"
        assert catalog_item["title"] == "Seed Entry"

    await state_engine.dispose()
    await index_engine.dispose()


async def test_collection_item_null_resource_id_does_not_violate_constraint(tmp_path):
    """item_type='catalog_entry' 时 resource_id 为 NULL 不违反唯一约束（多个 NULL 允许）。"""
    state_engine, index_engine, state_factory, index_factory = await _bootstrap(tmp_path)
    async with state_factory() as state:
        state.add(Collection(id=200, name="Catalog Only", description="", cover="", status="active", visible_on_home=True, sort_order=0))
        state.add(CollectionItem(id=10, collection_id=200, item_type="catalog_entry", catalog_entry_id="ce-a", resource_id=None, sort_order=0))
        state.add(CollectionItem(id=11, collection_id=200, item_type="catalog_entry", catalog_entry_id="ce-b", resource_id=None, sort_order=1))
        await state.commit()

        rows = list((await state.scalars(select(CollectionItem).where(CollectionItem.collection_id == 200))).all())
        assert len(rows) == 2
        assert all(row.resource_id is None for row in rows)

    await state_engine.dispose()
    await index_engine.dispose()


async def test_collection_topic_fields_read_write(tmp_path, monkeypatch):
    """专题字段 goal/audience/prerequisites/item_intro 读写（service + HTTP 路由）。"""
    state_engine, index_engine, state_factory, index_factory = await _bootstrap(tmp_path)
    user_token = await _seed_user(state_factory)
    async with state_factory() as state:
        state.add(Collection(
            id=300,
            name="工具配置入门",
            description="从零搭建工具链",
            cover="",
            status="active",
            visible_on_home=True,
            sort_order=0,
            goal="完成常用工具安装",
            audience="刚搭建环境的开发者",
            prerequisites="一台可联网电脑",
            item_intro="按顺序安装以下工具",
        ))
        await state.commit()
    _patch_sessions(monkeypatch, state_factory, index_factory)

    async with state_factory() as state, index_factory() as index:
        collection = await state.get(Collection, 300)
        payload = await collection_dict(state, index, collection, include_items=True)
        assert payload["goal"] == "完成常用工具安装"
        assert payload["audience"] == "刚搭建环境的开发者"
        assert payload["prerequisites"] == "一台可联网电脑"
        assert payload["item_intro"] == "按顺序安装以下工具"

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(USER_SESSION_COOKIE, user_token)
        response = await client.get("/api/collections/300")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["goal"] == "完成常用工具安装"
        assert body["audience"] == "刚搭建环境的开发者"
        assert body["prerequisites"] == "一台可联网电脑"
        assert body["item_intro"] == "按顺序安装以下工具"

    await state_engine.dispose()
    await index_engine.dispose()


async def test_seed_default_collections_three_topics_queryable(tmp_path, monkeypatch):
    """3 个种子专题可查询，每个专题条目数与 seed 定义一致。"""
    state_engine, index_engine, state_factory, index_factory = await _bootstrap(tmp_path)
    user_token = await _seed_user(state_factory)
    async with state_factory() as state:
        wrote = await seed_default_collections(state)
        assert wrote is True
        idempotent = await seed_default_collections(state)
        assert idempotent is False

    _patch_sessions(monkeypatch, state_factory, index_factory)

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(USER_SESSION_COOKIE, user_token)
        response = await client.get("/api/collections")
        assert response.status_code == 200, response.text
        items = response.json()["items"]
        assert len(items) == 3
        names = [item["name"] for item in items]
        assert names == ["工具配置入门", "技能学习路径", "项目素材准备"]

        for item in items:
            assert item["goal"]
            assert item["audience"]
            assert item["prerequisites"]
            assert item["item_intro"]
            assert item["item_count"] > 0

        detail = await client.get(f"/api/collections/{items[0]['id']}")
        assert detail.status_code == 200, detail.text
        detail_body = detail.json()
        assert detail_body["item_count"] == len(detail_body["items"])
        assert all(entry["item_type"] == "catalog_entry" for entry in detail_body["items"])

    await state_engine.dispose()
    await index_engine.dispose()


async def test_collection_item_removal_count_correct(tmp_path, monkeypatch):
    """移除条目后计数正确（service + HTTP 路由）。"""
    state_engine, index_engine, state_factory, index_factory = await _bootstrap(tmp_path)
    user_token = await _seed_user(state_factory)
    async with state_factory() as state, index_factory() as index:
        state.add(ContentRootMapping(id=1, content_type="software", display_name="Public", alist_path="/public", enabled=True))
        state.add(Collection(id=400, name="Removal Topic", description="", cover="", status="active", visible_on_home=True, sort_order=0))
        for idx in range(3):
            rid = f"res-{idx}"
            state.add(CollectionItem(id=idx + 1, collection_id=400, item_type="resource", resource_id=rid, sort_order=idx))
            index.add(Resource(id=rid, root_mapping_id=1, name=f"file-{idx}.zip", path=f"/public/file-{idx}.zip", content_type="software", status="active"))
        await state.commit()
        await index.commit()

        collection = await state.get(Collection, 400)
        before = await collection_dict(state, index, collection, include_items=True)
        assert before["item_count"] == 3

        await state.execute(delete(CollectionItem).where(CollectionItem.id == 1))
        await state.commit()

        after = await collection_dict(state, index, collection, include_items=True)
        assert after["item_count"] == 2
        assert len(after["items"]) == 2

    _patch_sessions(monkeypatch, state_factory, index_factory)
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(USER_SESSION_COOKIE, user_token)
        response = await client.get("/api/collections/400")
        assert response.status_code == 200, response.text
        assert response.json()["item_count"] == 2

    await state_engine.dispose()
    await index_engine.dispose()
