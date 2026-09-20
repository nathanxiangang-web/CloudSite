"""A4 content quality admin route end-to-end tests.

 Covers: todo list/detail/dismiss/resolve/batch-dismiss, detection trigger,
 detection run list, feedback list/review, user feedback submission,
 admin auth required, user auth required.
"""
from __future__ import annotations

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import auth, main
from cloudsite.database import IndexBase, StateBase
from cloudsite.models import (
    CatalogEntry,
    ContentRootMapping,
    SiteSettings,
    SystemSetting,
    User,
    utcnow,
)
from cloudsite.sessions import USER_SESSION_COOKIE, create_user_session

ORIGIN = {"Origin": "http://testserver"}


def _admin_cookies():
    return {main.SESSION_COOKIE: main.create_session_token("admin")}


async def _setup(monkeypatch):
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
        state.add(CatalogEntry(
            entry_id="ce_testentry00000000000000001",
            content_type="software",
            slug="test-entry",
            title="Test Entry",
            summary="",
            description="",
            status="published",
            revision=1,
        ))
        user = User(username="alice", username_normalized="alice", password_hash="x", status="active", created_at=utcnow(), updated_at=utcnow())
        state.add(user)
        await state.flush()
        _, user_token = await create_user_session(state, user.id, utcnow())
        await state.commit()

    transport = httpx.ASGITransport(app=main.app)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    user_cookies = {USER_SESSION_COOKIE: user_token}
    return client, state_engine, index_engine, user_cookies


# ---- auth tests ----

async def test_admin_routes_require_auth(monkeypatch):
    client, _, _, _ = await _setup(monkeypatch)
    resp = await client.get("/api/admin/quality/todos")
    assert resp.status_code == 403
    await client.aclose()


async def test_user_feedback_requires_auth(monkeypatch):
    client, _, _, _ = await _setup(monkeypatch)
    resp = await client.post(
        "/api/me/quality/feedback",
        json={"target_type": "entry", "target_id": "ce_test", "feedback_kind": "other", "description": "test"},
        headers=ORIGIN,
    )
    assert resp.status_code == 401
    await client.aclose()


# ---- detection + todo tests ----

async def test_detect_and_list_todos(monkeypatch):
    client, _, _, _ = await _setup(monkeypatch)
    resp = await client.post(
        "/api/admin/quality/detect",
        json={"budget_ms": 10000},
        cookies=_admin_cookies(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["items_found"] >= 1

    resp = await client.get(
        "/api/admin/quality/todos",
        cookies=_admin_cookies(),
    )
    assert resp.status_code == 200
    todos = resp.json()
    assert todos["total"] >= 1
    assert any(t["todo_type"] == "missing_description" for t in todos["items"])
    await client.aclose()


async def test_get_todo_detail(monkeypatch):
    client, _, _, _ = await _setup(monkeypatch)
    await client.post("/api/admin/quality/detect", json={"budget_ms": 10000}, cookies=_admin_cookies())
    resp = await client.get("/api/admin/quality/todos", cookies=_admin_cookies())
    todo_id = resp.json()["items"][0]["todo_id"]

    resp = await client.get(f"/api/admin/quality/todos/{todo_id}", cookies=_admin_cookies())
    assert resp.status_code == 200
    assert resp.json()["todo_id"] == todo_id
    await client.aclose()


async def test_dismiss_todo(monkeypatch):
    client, _, _, _ = await _setup(monkeypatch)
    await client.post("/api/admin/quality/detect", json={"budget_ms": 10000}, cookies=_admin_cookies())
    resp = await client.get("/api/admin/quality/todos", cookies=_admin_cookies())
    todo_id = resp.json()["items"][0]["todo_id"]

    resp = await client.post(
        f"/api/admin/quality/todos/{todo_id}/dismiss",
        json={"reason": "false positive"},
        cookies=_admin_cookies(),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "dismissed"

    resp = await client.get("/api/admin/quality/todos", cookies=_admin_cookies(), params={"status": "open"})
    assert resp.json()["total"] == 0
    await client.aclose()


async def test_resolve_todo(monkeypatch):
    client, _, _, _ = await _setup(monkeypatch)
    await client.post("/api/admin/quality/detect", json={"budget_ms": 10000}, cookies=_admin_cookies())
    resp = await client.get("/api/admin/quality/todos", cookies=_admin_cookies())
    todo_id = resp.json()["items"][0]["todo_id"]

    resp = await client.post(
        f"/api/admin/quality/todos/{todo_id}/resolve",
        cookies=_admin_cookies(),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "resolved"
    await client.aclose()


async def test_batch_dismiss(monkeypatch):
    client, _, _, _ = await _setup(monkeypatch)
    await client.post("/api/admin/quality/detect", json={"budget_ms": 10000}, cookies=_admin_cookies())
    resp = await client.get("/api/admin/quality/todos", cookies=_admin_cookies())
    todos = resp.json()["items"]
    ids = [t["todo_id"] for t in todos]

    resp = await client.post(
        "/api/admin/quality/todos/batch-dismiss",
        json={"todo_ids": ids, "reason": "batch"},
        cookies=_admin_cookies(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["succeeded"] == len(ids)
    assert data["failed"] == 0
    await client.aclose()


async def test_todo_not_found(monkeypatch):
    client, _, _, _ = await _setup(monkeypatch)
    resp = await client.get(
        "/api/admin/quality/todos/ct_nonexistent00000000000000000000",
        cookies=_admin_cookies(),
    )
    assert resp.status_code == 404
    await client.aclose()


# ---- detection run tests ----

async def test_list_detection_runs(monkeypatch):
    client, _, _, _ = await _setup(monkeypatch)
    await client.post("/api/admin/quality/detect", json={"budget_ms": 10000}, cookies=_admin_cookies())
    resp = await client.get("/api/admin/quality/detection-runs", cookies=_admin_cookies())
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert data["items"][0]["status"] == "completed"
    await client.aclose()


# ---- feedback tests ----

async def test_user_submit_feedback(monkeypatch):
    client, _, _, user_cookies = await _setup(monkeypatch)
    resp = await client.post(
        "/api/me/quality/feedback",
        json={
            "target_type": "entry",
            "target_id": "ce_testentry00000000000000001",
            "feedback_kind": "missing_content",
            "description": "This entry needs a description",
        },
        headers=ORIGIN,
        cookies=user_cookies,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "pending"
    assert data["todo_id"] is not None
    await client.aclose()


async def test_admin_list_feedback(monkeypatch):
    client, _, _, user_cookies = await _setup(monkeypatch)
    await client.post(
        "/api/me/quality/feedback",
        json={
            "target_type": "entry",
            "target_id": "ce_testentry00000000000000001",
            "feedback_kind": "broken_link",
            "description": "Link broken",
        },
        headers=ORIGIN,
        cookies=user_cookies,
    )
    resp = await client.get("/api/admin/quality/feedback", cookies=_admin_cookies())
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["feedback_kind"] == "broken_link"
    await client.aclose()


async def test_admin_review_feedback(monkeypatch):
    client, _, _, user_cookies = await _setup(monkeypatch)
    resp = await client.post(
        "/api/me/quality/feedback",
        json={
            "target_type": "entry",
            "target_id": "ce_testentry00000000000000001",
            "feedback_kind": "wrong_info",
            "description": "Info is wrong",
        },
        headers=ORIGIN,
        cookies=user_cookies,
    )
    feedback_id = resp.json()["feedback_id"]

    resp = await client.post(
        f"/api/admin/quality/feedback/{feedback_id}/review",
        json={"admin_note": "fixed", "status": "resolved"},
        cookies=_admin_cookies(),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "resolved"
    await client.aclose()


async def test_feedback_filter_by_status(monkeypatch):
    client, _, _, user_cookies = await _setup(monkeypatch)
    await client.post(
        "/api/me/quality/feedback",
        json={
            "target_type": "entry",
            "target_id": "ce_testentry00000000000000001",
            "feedback_kind": "other",
            "description": "test",
        },
        headers=ORIGIN,
        cookies=user_cookies,
    )
    resp = await client.get(
        "/api/admin/quality/feedback",
        params={"status": "pending"},
        cookies=_admin_cookies(),
    )
    assert resp.json()["total"] == 1
    resp = await client.get(
        "/api/admin/quality/feedback",
        params={"status": "resolved"},
        cookies=_admin_cookies(),
    )
    assert resp.json()["total"] == 0
    await client.aclose()


async def test_admin_list_feedback(monkeypatch):
    client, _, _, user_cookies = await _setup(monkeypatch)
    await client.post(
        "/api/me/quality/feedback",
        json={
            "target_type": "entry",
            "target_id": "ce_testentry00000000000000001",
            "feedback_kind": "broken_link",
            "description": "Link broken",
        },
        headers=ORIGIN,
        cookies=user_cookies,
    )
    resp = await client.get("/api/admin/quality/feedback", cookies=_admin_cookies())
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["feedback_kind"] == "broken_link"
    await client.aclose()


async def test_admin_review_feedback(monkeypatch):
    client, _, _, user_cookies = await _setup(monkeypatch)
    resp = await client.post(
        "/api/me/quality/feedback",
        json={
            "target_type": "entry",
            "target_id": "ce_testentry00000000000000001",
            "feedback_kind": "wrong_info",
            "description": "Info is wrong",
        },
        headers=ORIGIN,
        cookies=user_cookies,
    )
    feedback_id = resp.json()["feedback_id"]

    resp = await client.post(
        f"/api/admin/quality/feedback/{feedback_id}/review",
        json={"admin_note": "fixed", "status": "resolved"},
        cookies=_admin_cookies(),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "resolved"
    await client.aclose()


async def test_feedback_filter_by_status(monkeypatch):
    client, _, _, user_cookies = await _setup(monkeypatch)
    await client.post(
        "/api/me/quality/feedback",
        json={
            "target_type": "entry",
            "target_id": "ce_testentry00000000000000001",
            "feedback_kind": "other",
            "description": "test",
        },
        headers=ORIGIN,
        cookies=user_cookies,
    )
    resp = await client.get(
        "/api/admin/quality/feedback",
        params={"status": "pending"},
        cookies=_admin_cookies(),
    )
    assert resp.json()["total"] == 1
    resp = await client.get(
        "/api/admin/quality/feedback",
        params={"status": "resolved"},
        cookies=_admin_cookies(),
    )
    assert resp.json()["total"] == 0
    await client.aclose()