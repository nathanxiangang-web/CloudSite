"""A3 AI completion admin route end-to-end tests."""
from __future__ import annotations

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import auth, main
from cloudsite.database import StateBase
from cloudsite.models import CatalogEntry, ContentRootMapping, SiteSettings, SystemSetting

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
        await conn.run_sync(StateBase.metadata.create_all)
    monkeypatch.setattr(main, "StateSession", state_factory)
    monkeypatch.setattr(auth, "StateSession", state_factory)
    monkeypatch.setattr(main, "IndexSession", index_factory)

    async with state_factory() as state:
        state.add(SiteSettings(id=1))
        state.add(SystemSetting(key="setup_completed", value="true", value_type="string"))
        state.add(ContentRootMapping(id=1, content_type="software", display_name="root", alist_path="/root", enabled=True))
        state.add(CatalogEntry(
            entry_id="ce_testentry00000000000000001",
            content_type="software", slug="test-entry", title="Test Entry",
            summary="", description="", status="published", revision=1,
        ))
        await state.commit()

    transport = httpx.ASGITransport(app=main.app)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    return client, state_engine, index_engine


# ---- auth ----

async def test_admin_routes_require_auth(monkeypatch):
    client, _, _ = await _setup(monkeypatch)
    resp = await client.get("/api/admin/ai/configs")
    assert resp.status_code == 403
    await client.aclose()


# ---- config CRUD ----

async def test_create_and_list_config(monkeypatch):
    client, _, _ = await _setup(monkeypatch)
    resp = await client.post(
        "/api/admin/ai/configs",
        json={"provider_type": "local_ollama", "display_name": "Local", "enabled": True},
        cookies=_admin_cookies(),
    )
    assert resp.status_code == 201
    config_id = resp.json()["config_id"]

    resp = await client.get("/api/admin/ai/configs", cookies=_admin_cookies())
    assert resp.json()["total"] == 1
    await client.aclose()


async def test_update_config(monkeypatch):
    client, _, _ = await _setup(monkeypatch)
    resp = await client.post(
        "/api/admin/ai/configs",
        json={"provider_type": "local_ollama", "display_name": "Local", "enabled": False},
        cookies=_admin_cookies(),
    )
    config_id = resp.json()["config_id"]

    resp = await client.patch(
        f"/api/admin/ai/configs/{config_id}",
        json={"enabled": True},
        cookies=_admin_cookies(),
    )
    assert resp.status_code == 200
    assert resp.json()["enabled"] is True
    await client.aclose()


async def test_delete_config(monkeypatch):
    client, _, _ = await _setup(monkeypatch)
    resp = await client.post(
        "/api/admin/ai/configs",
        json={"provider_type": "local_ollama", "display_name": "Local"},
        cookies=_admin_cookies(),
    )
    config_id = resp.json()["config_id"]

    resp = await client.delete(f"/api/admin/ai/configs/{config_id}", cookies=_admin_cookies())
    assert resp.status_code == 204
    await client.aclose()


async def test_config_not_found(monkeypatch):
    client, _, _ = await _setup(monkeypatch)
    resp = await client.get(
        "/api/admin/ai/configs/ac_nonexistent00000000000000000000",
        cookies=_admin_cookies(),
    )
    assert resp.status_code == 404
    await client.aclose()


# ---- draft generation and review ----

async def test_generate_draft(monkeypatch):
    client, _, _ = await _setup(monkeypatch)
    await client.post(
        "/api/admin/ai/configs",
        json={"provider_type": "local_ollama", "display_name": "Local", "enabled": True},
        cookies=_admin_cookies(),
    )
    resp = await client.post(
        "/api/admin/ai/drafts/generate",
        json={
            "target_entry_id": "ce_testentry00000000000000001",
            "field_type": "summary",
            "generated_content": "AI summary",
            "tokens_used": 50,
        },
        cookies=_admin_cookies(),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"
    await client.aclose()


async def test_generate_no_provider(monkeypatch):
    client, _, _ = await _setup(monkeypatch)
    resp = await client.post(
        "/api/admin/ai/drafts/generate",
        json={"target_entry_id": "ce_testentry00000000000000001", "field_type": "summary"},
        cookies=_admin_cookies(),
    )
    assert resp.status_code == 409
    await client.aclose()


async def test_accept_draft(monkeypatch):
    client, _, _ = await _setup(monkeypatch)
    await client.post(
        "/api/admin/ai/configs",
        json={"provider_type": "local_ollama", "display_name": "Local", "enabled": True},
        cookies=_admin_cookies(),
    )
    resp = await client.post(
        "/api/admin/ai/drafts/generate",
        json={
            "target_entry_id": "ce_testentry00000000000000001",
            "field_type": "summary",
            "generated_content": "AI summary",
        },
        cookies=_admin_cookies(),
    )
    draft_id = resp.json()["draft_id"]

    resp = await client.post(f"/api/admin/ai/drafts/{draft_id}/accept", cookies=_admin_cookies())
    assert resp.status_code == 200
    assert resp.json()["candidate_status"] == "accepted"
    await client.aclose()


async def test_reject_draft(monkeypatch):
    client, _, _ = await _setup(monkeypatch)
    await client.post(
        "/api/admin/ai/configs",
        json={"provider_type": "local_ollama", "display_name": "Local", "enabled": True},
        cookies=_admin_cookies(),
    )
    resp = await client.post(
        "/api/admin/ai/drafts/generate",
        json={
            "target_entry_id": "ce_testentry00000000000000001",
            "field_type": "tags",
            "generated_content": "tag1, tag2",
        },
        cookies=_admin_cookies(),
    )
    draft_id = resp.json()["draft_id"]

    resp = await client.post(
        f"/api/admin/ai/drafts/{draft_id}/reject",
        json={"reason": "inaccurate"},
        cookies=_admin_cookies(),
    )
    assert resp.status_code == 200
    assert resp.json()["candidate_status"] == "rejected"
    await client.aclose()


async def test_modify_draft(monkeypatch):
    client, _, _ = await _setup(monkeypatch)
    await client.post(
        "/api/admin/ai/configs",
        json={"provider_type": "local_ollama", "display_name": "Local", "enabled": True},
        cookies=_admin_cookies(),
    )
    resp = await client.post(
        "/api/admin/ai/drafts/generate",
        json={
            "target_entry_id": "ce_testentry00000000000000001",
            "field_type": "summary",
            "generated_content": "original",
        },
        cookies=_admin_cookies(),
    )
    draft_id = resp.json()["draft_id"]

    resp = await client.post(
        f"/api/admin/ai/drafts/{draft_id}/modify",
        json={"modified_content": "corrected"},
        cookies=_admin_cookies(),
    )
    assert resp.status_code == 200
    assert resp.json()["candidate_status"] == "modified"
    await client.aclose()


async def test_list_drafts(monkeypatch):
    client, _, _ = await _setup(monkeypatch)
    await client.post(
        "/api/admin/ai/configs",
        json={"provider_type": "local_ollama", "display_name": "Local", "enabled": True},
        cookies=_admin_cookies(),
    )
    await client.post(
        "/api/admin/ai/drafts/generate",
        json={
            "target_entry_id": "ce_testentry00000000000000001",
            "field_type": "summary",
            "generated_content": "s",
        },
        cookies=_admin_cookies(),
    )
    resp = await client.get("/api/admin/ai/drafts", cookies=_admin_cookies())
    assert resp.json()["total"] == 1
    await client.aclose()


async def test_budget_endpoint(monkeypatch):
    client, _, _ = await _setup(monkeypatch)
    resp = await client.post(
        "/api/admin/ai/configs",
        json={"provider_type": "local_ollama", "display_name": "Local", "enabled": True},
        cookies=_admin_cookies(),
    )
    config_id = resp.json()["config_id"]

    resp = await client.get(f"/api/admin/ai/configs/{config_id}/budget", cookies=_admin_cookies())
    assert resp.status_code == 200
    assert resp.json()["tokens_used"] == 0
    await client.aclose()