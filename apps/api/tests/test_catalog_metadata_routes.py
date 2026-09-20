"""Focused admin route tests for the C3 Catalog metadata API.

Covers tag lifecycle, assignment validation, duplicate relation, deletion audit,
revision pagination/filtering, and anonymous 403 through the real HTTP boundary.
"""
import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import auth, main
from cloudsite.database import StateBase
from cloudsite.models import CatalogEntry, CatalogRelation, CatalogRevision, CatalogTag, SiteSettings, SystemSetting


def _entry(entry_id: str, slug: str, status: str = "published") -> CatalogEntry:
    return CatalogEntry(
        entry_id=entry_id,
        content_type="software",
        slug=slug,
        title=slug,
        status=status,
    )


async def _setup(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    async with factory() as state:
        state.add_all(
            [
                SiteSettings(id=1),
                SystemSetting(key="setup_completed", value="true", value_type="string"),
            ]
        )
        await state.commit()
    monkeypatch.setattr(main, "StateSession", factory)
    monkeypatch.setattr(auth, "StateSession", factory)
    transport = httpx.ASGITransport(app=main.app)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    return client, engine, factory


def _admin_cookies() -> dict:
    return {main.SESSION_COOKIE: main.create_session_token("admin")}


async def test_tag_lifecycle_create_update_delete(monkeypatch):
    client, engine, factory = await _setup(monkeypatch)
    async with client:
        client.cookies.set(main.SESSION_COOKIE, main.create_session_token("admin"))
        created = await client.post(
            "/api/admin/catalog/metadata/tags",
            json={"slug": "stable", "display_name": "Stable"},
        )
        assert created.status_code == 201, created.text
        tag = created.json()
        assert tag["slug"] == "stable"
        tag_id = tag["tag_id"]

        listed = await client.get("/api/admin/catalog/metadata/tags")
        assert listed.status_code == 200, listed.text
        assert len(listed.json()) == 1

        updated = await client.patch(
            f"/api/admin/catalog/metadata/tags/{tag_id}",
            json={"display_name": "Stable Release"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["display_name"] == "Stable Release"

        conflict = await client.post(
            "/api/admin/catalog/metadata/tags",
            json={"slug": "stable", "display_name": "Dup"},
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "CATALOG_METADATA_CONFLICT"

        deleted = await client.delete(f"/api/admin/catalog/metadata/tags/{tag_id}")
        assert deleted.status_code == 204

        missing = await client.get("/api/admin/catalog/metadata/tags")
        assert missing.status_code == 200
        assert len(missing.json()) == 0

        not_found = await client.patch(
            f"/api/admin/catalog/metadata/tags/{tag_id}",
            json={"display_name": "Ghost"},
        )
        assert not_found.status_code == 404
        assert not_found.json()["detail"]["code"] == "CATALOG_METADATA_NOT_FOUND"
    await engine.dispose()


async def test_tag_update_rejects_bad_slug(monkeypatch):
    client, engine, factory = await _setup(monkeypatch)
    async with client:
        client.cookies.set(main.SESSION_COOKIE, main.create_session_token("admin"))
        created = await client.post(
            "/api/admin/catalog/metadata/tags",
            json={"slug": "good", "display_name": "Good"},
        )
        tag_id = created.json()["tag_id"]
        bad = await client.patch(
            f"/api/admin/catalog/metadata/tags/{tag_id}",
            json={"slug": "Bad Slug"},
        )
        assert bad.status_code == 422
    await engine.dispose()


async def test_tag_assignment_validation_and_idempotency(monkeypatch):
    client, engine, factory = await _setup(monkeypatch)
    entry_id = "ce_" + "a" * 32
    async with factory() as state:
        state.add(_entry(entry_id, "assigned-entry"))
        await state.commit()
    async with client:
        client.cookies.set(main.SESSION_COOKIE, main.create_session_token("admin"))
        tag = await client.post(
            "/api/admin/catalog/metadata/tags",
            json={"slug": "featured", "display_name": "Featured"},
        )
        tag_id = tag.json()["tag_id"]

        assigned = await client.post(
            "/api/admin/catalog/metadata/tags/assignments",
            json={"tag_id": tag_id, "target_type": "entry", "target_id": entry_id},
        )
        assert assigned.status_code == 201, assigned.text

        again = await client.post(
            "/api/admin/catalog/metadata/tags/assignments",
            json={"tag_id": tag_id, "target_type": "entry", "target_id": entry_id},
        )
        assert again.status_code == 201
        assert again.json()["tag_id"] == tag_id

        bad_target = await client.post(
            "/api/admin/catalog/metadata/tags/assignments",
            json={"tag_id": tag_id, "target_type": "entry", "target_id": "ce_" + "9" * 32},
        )
        assert bad_target.status_code == 404
        assert bad_target.json()["detail"]["code"] == "CATALOG_METADATA_NOT_FOUND"

        bad_type = await client.post(
            "/api/admin/catalog/metadata/tags/assignments",
            json={"tag_id": tag_id, "target_type": "unknown", "target_id": entry_id},
        )
        assert bad_type.status_code == 422

        unassigned = await client.request(
            "DELETE",
            "/api/admin/catalog/metadata/tags/assignments",
            json={"tag_id": tag_id, "target_type": "entry", "target_id": entry_id},
        )
        assert unassigned.status_code == 204

        again_unassign = await client.request(
            "DELETE",
            "/api/admin/catalog/metadata/tags/assignments",
            json={"tag_id": tag_id, "target_type": "entry", "target_id": entry_id},
        )
        assert again_unassign.status_code == 204
    await engine.dispose()


async def test_relation_create_duplicate_and_delete_audit(monkeypatch):
    client, engine, factory = await _setup(monkeypatch)
    first_id = "ce_" + "1" * 32
    second_id = "ce_" + "2" * 32
    async with factory() as state:
        state.add_all([_entry(first_id, "source"), _entry(second_id, "target")])
        await state.commit()
    async with client:
        client.cookies.set(main.SESSION_COOKIE, main.create_session_token("admin"))
        created = await client.post(
            "/api/admin/catalog/metadata/relations",
            json={
                "from_entry_id": first_id,
                "to_entry_id": second_id,
                "relation_type": "companion",
                "note": "see also",
            },
        )
        assert created.status_code == 201, created.text
        relation_id = created.json()["relation_id"]

        duplicate = await client.post(
            "/api/admin/catalog/metadata/relations",
            json={
                "from_entry_id": first_id,
                "to_entry_id": second_id,
                "relation_type": "companion",
            },
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["detail"]["code"] == "CATALOG_METADATA_CONFLICT"

        listed = await client.get("/api/admin/catalog/metadata/relations")
        assert listed.status_code == 200
        assert len(listed.json()) == 1

        filtered = await client.get(
            "/api/admin/catalog/metadata/relations",
            params={"from_entry_id": first_id},
        )
        assert len(filtered.json()) == 1

        deleted = await client.delete(f"/api/admin/catalog/metadata/relations/{relation_id}")
        assert deleted.status_code == 204

        not_found = await client.delete(f"/api/admin/catalog/metadata/relations/{relation_id}")
        assert not_found.status_code == 404

    async with factory() as state:
        from sqlalchemy import select

        revisions = list((await state.scalars(select(CatalogRevision).where(
            CatalogRevision.target_type == "relation"
        ))).all())
        assert [r.action for r in revisions] == ["create", "delete"]
    await engine.dispose()


async def test_relation_rejects_self_reference(monkeypatch):
    client, engine, factory = await _setup(monkeypatch)
    entry_id = "ce_" + "3" * 32
    async with factory() as state:
        state.add(_entry(entry_id, "solo"))
        await state.commit()
    async with client:
        client.cookies.set(main.SESSION_COOKIE, main.create_session_token("admin"))
        self_rel = await client.post(
            "/api/admin/catalog/metadata/relations",
            json={
                "from_entry_id": entry_id,
                "to_entry_id": entry_id,
                "relation_type": "variant",
            },
        )
        assert self_rel.status_code == 400
        assert self_rel.json()["detail"]["code"] == "CATALOG_METADATA_INVALID"
    await engine.dispose()


async def test_revision_pagination_and_filtering(monkeypatch):
    client, engine, factory = await _setup(monkeypatch)
    async with client:
        client.cookies.set(main.SESSION_COOKIE, main.create_session_token("admin"))
        tag = await client.post(
            "/api/admin/catalog/metadata/tags",
            json={"slug": "versioned", "display_name": "Versioned"},
        )
        tag_id = tag.json()["tag_id"]
        await client.patch(
            f"/api/admin/catalog/metadata/tags/{tag_id}",
            json={"display_name": "Versioned 2"},
        )

        page1 = await client.get("/api/admin/catalog/metadata/revisions", params={"page": 1, "page_size": 1})
        assert page1.status_code == 200, page1.text
        body = page1.json()
        assert body["total"] == 2
        assert body["total_pages"] == 2
        assert len(body["items"]) == 1
        assert body["items"][0]["action"] == "create"

        page2 = await client.get("/api/admin/catalog/metadata/revisions", params={"page": 2, "page_size": 1})
        assert page2.json()["items"][0]["action"] == "update"

        filtered = await client.get(
            "/api/admin/catalog/metadata/revisions",
            params={"target_type": "tag", "target_id": tag_id},
        )
        assert filtered.json()["total"] == 2

        action_filter = await client.get(
            "/api/admin/catalog/metadata/revisions",
            params={"action": "update"},
        )
        assert action_filter.json()["total"] == 1
        assert action_filter.json()["items"][0]["action"] == "update"
    await engine.dispose()


async def test_revisions_filter_rejects_bad_target_type(monkeypatch):
    client, engine, factory = await _setup(monkeypatch)
    async with client:
        client.cookies.set(main.SESSION_COOKIE, main.create_session_token("admin"))
        bad = await client.get(
            "/api/admin/catalog/metadata/revisions",
            params={"target_type": "bogus"},
        )
        assert bad.status_code == 400
        assert bad.json()["detail"]["code"] == "CATALOG_METADATA_INVALID"
    await engine.dispose()


async def test_metadata_endpoints_reject_anonymous(monkeypatch):
    client, engine, factory = await _setup(monkeypatch)
    async with client:
        for method, path in [
            ("GET", "/api/admin/catalog/metadata/tags"),
            ("POST", "/api/admin/catalog/metadata/tags"),
            ("PATCH", "/api/admin/catalog/metadata/tags/ct_" + "0" * 32),
            ("DELETE", "/api/admin/catalog/metadata/tags/ct_" + "0" * 32),
            ("POST", "/api/admin/catalog/metadata/tags/assignments"),
            ("DELETE", "/api/admin/catalog/metadata/tags/assignments"),
            ("GET", "/api/admin/catalog/metadata/relations"),
            ("POST", "/api/admin/catalog/metadata/relations"),
            ("DELETE", "/api/admin/catalog/metadata/relations/cx_" + "0" * 32),
            ("GET", "/api/admin/catalog/metadata/revisions"),
        ]:
            response = await client.request(method, path)
            assert response.status_code == 403, f"{method} {path} -> {response.status_code}"
            assert response.json()["detail"]["code"] == "ADMIN_REQUIRED"
    await engine.dispose()


async def test_tag_schema_forbids_extra_fields(monkeypatch):
    client, engine, factory = await _setup(monkeypatch)
    async with client:
        client.cookies.set(main.SESSION_COOKIE, main.create_session_token("admin"))
        response = await client.post(
            "/api/admin/catalog/metadata/tags",
            json={"slug": "x", "display_name": "X", "url": "https://evil.example"},
        )
        assert response.status_code == 422
    await engine.dispose()
