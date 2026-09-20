"""A2 整理工作台管理员路由端到端测试。

覆盖 9 个端点：建议列表（五类分页）、详情、单条/批量 apply、单条/批量 reject、
撤销、撤销记录、触发生成。验证批量逐项返回、幂等、影子模式、仅管理员。
"""
from __future__ import annotations

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import auth, main
from cloudsite.database import IndexBase, StateBase
from cloudsite.models import (
    CatalogEntry,
    ContentRootMapping,
    Resource,
    SiteSettings,
    SystemSetting,
)

ORIGIN = {"Origin": "http://testserver"}
_BASE = "/api/admin/automation/suggestions"


def _admin_cookies():
    return {main.SESSION_COOKIE: main.create_session_token("admin")}


def _make_resource(rid, name="CloudSite-v1.2.3-windows-x64.msi", path=None):
    return Resource(
        id=rid,
        name=name,
        path=path or f"/root/{name}",
        parent_id=None,
        content_type="software",
        root_mapping_id=1,
        extension="msi",
        mime_type="application/x-msi",
        size=1024000,
        thumbnail="",
        status="active",
    )


async def _setup(monkeypatch, *, resources=None):
    state_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    index_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    index_factory = async_sessionmaker(index_engine, expire_on_commit=False)
    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)
    monkeypatch.setattr(main, "StateSession", state_factory)
    monkeypatch.setattr(auth, "StateSession", state_factory)
    monkeypatch.setattr(main, "IndexSession", index_factory)

    async with state_factory() as state:
        state.add(SiteSettings(id=1))
        state.add(SystemSetting(key="setup_completed", value="true", value_type="string"))
        state.add(ContentRootMapping(id=1, content_type="software", display_name="root", alist_path="/root", enabled=True))
        await state.commit()

    if resources is None:
        resources = [_make_resource("r_testresource0000000000000001")]
    async with index_factory() as index:
        index.add_all(resources)
        await index.commit()

    transport = httpx.ASGITransport(app=main.app)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    return client, state_engine, index_engine, state_factory


async def _generate(client):
    resp = await client.post(
        "/api/admin/automation/generate",
        json={"limit": 500},
        cookies=_admin_cookies(),
        headers=ORIGIN,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _list_ids(client):
    resp = await client.get(_BASE, cookies=_admin_cookies())
    assert resp.status_code == 200, resp.text
    return [item["suggestion_id"] for item in resp.json()["items"]]


async def test_generate_creates_suggestions(monkeypatch):
    client, state_engine, index_engine, _ = await _setup(monkeypatch)
    async with client:
        data = await _generate(client)
        assert data["created"] >= 1
    await state_engine.dispose()
    await index_engine.dispose()


async def test_generate_shadow_mode_does_not_touch_catalog(monkeypatch):
    client, state_engine, index_engine, state_factory = await _setup(monkeypatch)
    async with client:
        await _generate(client)
    async with state_factory() as state:
        entries = list((await state.scalars(select(CatalogEntry))).all())
        assert entries == [], "影子模式不应创建正式 catalog entry"
    await state_engine.dispose()
    await index_engine.dispose()


async def test_generate_is_idempotent_via_route(monkeypatch):
    client, state_engine, index_engine, _ = await _setup(monkeypatch)
    async with client:
        first = await _generate(client)
        second = await _generate(client)
        assert first["created"] >= 1
        assert second["created"] == 0
        assert second["skipped"] >= 1
    await state_engine.dispose()
    await index_engine.dispose()


async def test_suggestions_list_returns_paginated_envelope(monkeypatch):
    client, state_engine, index_engine, _ = await _setup(monkeypatch)
    async with client:
        await _generate(client)
        resp = await client.get(f"{_BASE}?page=1&page_size=10", cookies=_admin_cookies())
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["page"] == 1
        assert body["page_size"] == 10
        assert body["total"] >= 1
        assert body["total_pages"] >= 1
        assert isinstance(body["items"], list)
    await state_engine.dispose()
    await index_engine.dispose()


async def test_suggestions_list_kind_filter_isolates_five_categories(monkeypatch):
    resources = [
        _make_resource("r_aaaaaaaaaaaaaaaaaaaaaaaa000001", name="app-a-v1.0.zip", path="/root/app-a-v1.0.zip"),
        _make_resource("r_bbbbbbbbbbbbbbbbbbbbbbbb000002", name="app-b-v2.0.zip", path="/root/app-b-v2.0.zip"),
    ]
    client, state_engine, index_engine, _ = await _setup(monkeypatch, resources=resources)
    async with client:
        await _generate(client)
        for kind in ("new_entry", "new_release", "asset", "candidate_duplicate", "conflict"):
            resp = await client.get(f"{_BASE}?suggestion_kind={kind}", cookies=_admin_cookies())
            assert resp.status_code == 200, resp.text
            for item in resp.json()["items"]:
                assert item["suggestion_kind"] == kind, f"{kind} 筛选混入了 {item['suggestion_kind']}"
    await state_engine.dispose()
    await index_engine.dispose()


async def test_suggestions_list_status_filter(monkeypatch):
    client, state_engine, index_engine, _ = await _setup(monkeypatch)
    async with client:
        await _generate(client)
        resp = await client.get(f"{_BASE}?status=pending", cookies=_admin_cookies())
        assert resp.status_code == 200, resp.text
        for item in resp.json()["items"]:
            assert item["status"] == "pending"
    await state_engine.dispose()
    await index_engine.dispose()


async def test_suggestion_detail_returns_summary(monkeypatch):
    client, state_engine, index_engine, _ = await _setup(monkeypatch)
    async with client:
        await _generate(client)
        sid = (await _list_ids(client))[0]
        resp = await client.get(f"{_BASE}/{sid}", cookies=_admin_cookies())
        assert resp.status_code == 200, resp.text
        assert resp.json()["suggestion_id"] == sid
    await state_engine.dispose()
    await index_engine.dispose()


async def test_suggestion_detail_not_found_returns_404(monkeypatch):
    client, state_engine, index_engine, _ = await _setup(monkeypatch)
    async with client:
        resp = await client.get(f"{_BASE}/cs_nonexistent00000000000000000aaa", cookies=_admin_cookies())
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "SUGGESTION_NOT_FOUND"
    await state_engine.dispose()
    await index_engine.dispose()


async def test_apply_single_succeeds(monkeypatch):
    client, state_engine, index_engine, _ = await _setup(monkeypatch)
    async with client:
        await _generate(client)
        sid = (await _list_ids(client))[0]
        resp = await client.post(f"{_BASE}/{sid}/apply", cookies=_admin_cookies(), headers=ORIGIN)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is True
        assert body["entry_id"] is not None
    await state_engine.dispose()
    await index_engine.dispose()


async def test_apply_is_idempotent(monkeypatch):
    client, state_engine, index_engine, _ = await _setup(monkeypatch)
    async with client:
        await _generate(client)
        sid = (await _list_ids(client))[0]
        r1 = await client.post(f"{_BASE}/{sid}/apply", cookies=_admin_cookies(), headers=ORIGIN)
        assert r1.status_code == 200, r1.text
        r2 = await client.post(f"{_BASE}/{sid}/apply", cookies=_admin_cookies(), headers=ORIGIN)
        assert r2.status_code == 200, r2.text
        assert r2.json()["success"] is True
        assert r1.json()["entry_id"] == r2.json()["entry_id"]
    await state_engine.dispose()
    await index_engine.dispose()


async def test_batch_apply_per_item_partial_failure(monkeypatch):
    resources = [
        _make_resource("r_aaaaaaaaaaaaaaaaaaaaaaaa000001", name="app-a-v1.0.zip", path="/root/app-a-v1.0.zip"),
        _make_resource("r_bbbbbbbbbbbbbbbbbbbbbbbb000002", name="app-b-v2.0.zip", path="/root/app-b-v2.0.zip"),
    ]
    client, state_engine, index_engine, _ = await _setup(monkeypatch, resources=resources)
    async with client:
        await _generate(client)
        ids = await _list_ids(client)
        assert len(ids) >= 2
        batch_ids = [ids[0], ids[1], "cs_nonexistent00000000000000000bbb"]
        resp = await client.post(
            f"{_BASE}/batch-apply",
            json={"suggestion_ids": batch_ids},
            cookies=_admin_cookies(),
            headers=ORIGIN,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["succeeded"] == 2
        assert body["failed"] == 1
        assert len(body["results"]) == 3
        failed_items = [r for r in body["results"] if not r["success"]]
        assert len(failed_items) == 1
        assert failed_items[0]["suggestion_id"] == "cs_nonexistent00000000000000000bbb"
        assert failed_items[0]["error"]
    await state_engine.dispose()
    await index_engine.dispose()


async def test_batch_apply_idempotent_does_not_fake_success(monkeypatch):
    client, state_engine, index_engine, _ = await _setup(monkeypatch)
    async with client:
        await _generate(client)
        sid = (await _list_ids(client))[0]
        await client.post(f"{_BASE}/{sid}/apply", cookies=_admin_cookies(), headers=ORIGIN)
        resp = await client.post(
            f"{_BASE}/batch-apply",
            json={"suggestion_ids": [sid]},
            cookies=_admin_cookies(),
            headers=ORIGIN,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["succeeded"] == 1
        assert body["results"][0]["success"] is True
    await state_engine.dispose()
    await index_engine.dispose()


async def test_reject_single(monkeypatch):
    client, state_engine, index_engine, _ = await _setup(monkeypatch)
    async with client:
        await _generate(client)
        sid = (await _list_ids(client))[0]
        resp = await client.post(
            f"{_BASE}/{sid}/reject",
            json={"reason": "不需要"},
            cookies=_admin_cookies(),
            headers=ORIGIN,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "rejected"
    await state_engine.dispose()
    await index_engine.dispose()


async def test_reject_is_idempotent(monkeypatch):
    client, state_engine, index_engine, _ = await _setup(monkeypatch)
    async with client:
        await _generate(client)
        sid = (await _list_ids(client))[0]
        r1 = await client.post(f"{_BASE}/{sid}/reject", json={"reason": ""}, cookies=_admin_cookies(), headers=ORIGIN)
        assert r1.status_code == 200, r1.text
        r2 = await client.post(f"{_BASE}/{sid}/reject", json={"reason": ""}, cookies=_admin_cookies(), headers=ORIGIN)
        assert r2.status_code == 200, r2.text
        assert r2.json()["status"] == "rejected"
    await state_engine.dispose()
    await index_engine.dispose()


async def test_batch_reject_per_item(monkeypatch):
    resources = [
        _make_resource("r_aaaaaaaaaaaaaaaaaaaaaaaa000001", name="app-a-v1.0.zip", path="/root/app-a-v1.0.zip"),
        _make_resource("r_bbbbbbbbbbbbbbbbbbbbbbbb000002", name="app-b-v2.0.zip", path="/root/app-b-v2.0.zip"),
    ]
    client, state_engine, index_engine, _ = await _setup(monkeypatch, resources=resources)
    async with client:
        await _generate(client)
        ids = await _list_ids(client)
        resp = await client.post(
            f"{_BASE}/batch-reject",
            json={"suggestion_ids": ids, "reason": "批量拒绝"},
            cookies=_admin_cookies(),
            headers=ORIGIN,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["succeeded"] == len(ids)
        assert body["failed"] == 0
    await state_engine.dispose()
    await index_engine.dispose()


async def test_batch_reject_partial_failure(monkeypatch):
    client, state_engine, index_engine, _ = await _setup(monkeypatch)
    async with client:
        await _generate(client)
        sid = (await _list_ids(client))[0]
        resp = await client.post(
            f"{_BASE}/batch-reject",
            json={"suggestion_ids": [sid, "cs_nonexistent00000000000000000ccc"]},
            cookies=_admin_cookies(),
            headers=ORIGIN,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["succeeded"] == 1
        assert body["failed"] == 1
    await state_engine.dispose()
    await index_engine.dispose()


async def test_revert_applied_suggestion(monkeypatch):
    client, state_engine, index_engine, _ = await _setup(monkeypatch)
    async with client:
        await _generate(client)
        sid = (await _list_ids(client))[0]
        await client.post(f"{_BASE}/{sid}/apply", cookies=_admin_cookies(), headers=ORIGIN)
        resp = await client.post(f"{_BASE}/{sid}/revert", cookies=_admin_cookies(), headers=ORIGIN)
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "reviewed"
    await state_engine.dispose()
    await index_engine.dispose()


async def test_revert_non_applied_returns_409(monkeypatch):
    client, state_engine, index_engine, _ = await _setup(monkeypatch)
    async with client:
        await _generate(client)
        sid = (await _list_ids(client))[0]
        resp = await client.post(f"{_BASE}/{sid}/revert", cookies=_admin_cookies(), headers=ORIGIN)
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "SUGGESTION_STATE_INVALID"
    await state_engine.dispose()
    await index_engine.dispose()


async def test_suggestion_revisions_after_apply(monkeypatch):
    client, state_engine, index_engine, _ = await _setup(monkeypatch)
    async with client:
        await _generate(client)
        sid = (await _list_ids(client))[0]
        await client.post(f"{_BASE}/{sid}/apply", cookies=_admin_cookies(), headers=ORIGIN)
        resp = await client.get(f"{_BASE}/{sid}/revisions", cookies=_admin_cookies())
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] >= 1
        assert isinstance(body["items"], list)
    await state_engine.dispose()
    await index_engine.dispose()


async def test_anonymous_request_rejected_403(monkeypatch):
    client, state_engine, index_engine, _ = await _setup(monkeypatch)
    async with client:
        resp_get = await client.get(_BASE)
        assert resp_get.status_code == 403
        assert resp_get.json()["detail"]["code"] == "ADMIN_REQUIRED"
        resp_post = await client.post("/api/admin/automation/generate", json={"limit": 10})
        assert resp_post.status_code == 403
        assert resp_post.json()["detail"]["code"] == "ADMIN_REQUIRED"
    await state_engine.dispose()
    await index_engine.dispose()


async def test_forged_admin_cookie_rejected_403(monkeypatch):
    client, state_engine, index_engine, _ = await _setup(monkeypatch)
    async with client:
        resp = await client.get(_BASE, cookies={main.SESSION_COOKIE: "fake.payload.sig"})
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "ADMIN_REQUIRED"
    await state_engine.dispose()
    await index_engine.dispose()
