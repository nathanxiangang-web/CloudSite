"""Deterministic browser-E2E seed route regression tests."""

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import main
from cloudsite.config import settings
from cloudsite.database import IndexBase, StateBase
from cloudsite.infrastructure.e2e_seed import E2E_RESOURCE_ID, E2E_RESOURCE_NAME
from cloudsite.models import User, utcnow
from cloudsite.modules.providers.infrastructure.models import ContentRootMapping
from cloudsite.modules.resources.infrastructure.models import Resource
from cloudsite.sessions import USER_SESSION_COOKIE, create_user_session


async def _stores(monkeypatch):
    state_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    index_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    index_factory = async_sessionmaker(index_engine, expire_on_commit=False)

    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)
        await conn.execute(
            text(
                "CREATE VIRTUAL TABLE search_fts USING fts5("
                "object_id UNINDEXED, object_type UNINDEXED, name, extension, "
                "content_type UNINDEXED, description, tags, breadcrumb_text)"
            )
        )

    monkeypatch.setattr(main, "StateSession", state_factory)
    monkeypatch.setattr(main, "IndexSession", index_factory)
    return state_engine, index_engine, state_factory, index_factory


async def test_e2e_seed_route_is_hidden_without_explicit_opt_in(monkeypatch):
    state_engine, index_engine, _, _ = await _stores(monkeypatch)
    monkeypatch.setattr(settings, "allow_insecure_dev_key", True)
    monkeypatch.setattr(settings, "e2e_seed_enabled", False)

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        disabled = await client.post(
            "/api/_e2e/seed",
            headers={"X-E2E-Run": "1"},
        )
        assert disabled.status_code == 404

        monkeypatch.setattr(settings, "e2e_seed_enabled", True)
        missing_header = await client.post("/api/_e2e/seed")
        assert missing_header.status_code == 404

        monkeypatch.setattr(settings, "allow_insecure_dev_key", False)
        production_mode = await client.post(
            "/api/_e2e/seed",
            headers={"X-E2E-Run": "1"},
        )
        assert production_mode.status_code == 404

    await state_engine.dispose()
    await index_engine.dispose()


async def test_e2e_seed_is_idempotent_and_visible_to_browse_search_detail(
    monkeypatch,
):
    state_engine, index_engine, state_factory, index_factory = await _stores(
        monkeypatch
    )
    monkeypatch.setattr(settings, "allow_insecure_dev_key", True)
    monkeypatch.setattr(settings, "e2e_seed_enabled", True)

    async with state_factory() as state:
        user = User(
            username="e2e",
            username_normalized="e2e",
            password_hash="not-used",
            status="active",
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        state.add(user)
        await state.flush()
        _, user_token = await create_user_session(state, user.id, utcnow())
        await state.commit()

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        first = await client.post(
            "/api/_e2e/seed",
            headers={"X-E2E-Run": "1"},
        )
        second = await client.post(
            "/api/_e2e/seed",
            headers={"X-E2E-Run": "1"},
        )
        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert first.json()["resource_id"] == E2E_RESOURCE_ID
        assert second.json()["root_mapping_id"] == first.json()["root_mapping_id"]
        assert first.json()["download_provider_seeded"] is False

        browse = await client.get(
            "/api/browse?page=1&page_size=24&sort=name&order=asc",
            cookies={USER_SESSION_COOKIE: user_token},
        )
        assert browse.status_code == 200, browse.text
        assert E2E_RESOURCE_ID in {
            item["id"] for item in browse.json()["items"]
        }

        search = await client.get(
            "/api/search",
            params={"q": "cloudsite-e2e-package"},
            cookies={USER_SESSION_COOKIE: user_token},
        )
        assert search.status_code == 200, search.text
        assert search.json()["total"] >= 1
        assert any(
            item["id"] == E2E_RESOURCE_ID
            and item["name"] == E2E_RESOURCE_NAME
            for item in search.json()["items"]
        )

        detail = await client.get(
            f"/api/resources/{E2E_RESOURCE_ID}",
            cookies={USER_SESSION_COOKIE: user_token},
        )
        assert detail.status_code == 200, detail.text
        assert detail.json()["name"] == E2E_RESOURCE_NAME
        assert detail.json()["capabilities"]["can_download"] is True

    async with state_factory() as state:
        root_count = await state.scalar(
            select(func.count(ContentRootMapping.id)).where(
                ContentRootMapping.alist_path == "/__cloudsite_e2e__"
            )
        )
        assert root_count == 1

    async with index_factory() as index:
        resource_count = await index.scalar(
            select(func.count(Resource.id)).where(
                Resource.id == E2E_RESOURCE_ID
            )
        )
        assert resource_count == 1

    await state_engine.dispose()
    await index_engine.dispose()
