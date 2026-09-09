"""Resource-detail sibling scope regression tests.

Verify that related/previous/next payloads for /api/resources/{id} never
include resources from another content root when the roots share parent_id
(None or an equivalent parent identifier). Covers two collision shapes:

1. Disabled root: a second root is disabled but its resources share the
   same parent_id as the enabled root's resources. The disabled root's
   resources must not appear as related/previous/next.
2. Enabled-root collision: both roots are enabled and share parent_id.
   Siblings must stay within the main resource's root_mapping_id so equal
   parent IDs across roots never mix.
"""
import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import auth, main
from cloudsite.database import IndexBase, StateBase
from cloudsite.models import ContentRootMapping, Resource, SiteSettings, User, utcnow
from cloudsite.sessions import USER_SESSION_COOKIE, create_user_session


async def _build_store(monkeypatch, *, second_root_enabled: bool):
    """Two roots sharing parent_id=None, each with three active resources."""
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
        state.add(ContentRootMapping(id=1, content_type="software", display_name="root-a", alist_path="/root-a", enabled=True))
        state.add(ContentRootMapping(id=2, content_type="software", display_name="root-b", alist_path="/root-b", enabled=second_root_enabled))
        user = User(username="user", username_normalized="user", password_hash="x", status="active", created_at=utcnow(), updated_at=utcnow())
        state.add(user)
        await state.flush()
        _, token = await create_user_session(state, user.id, utcnow())
        await state.commit()

    async with index_factory() as index:
        for rid, name, path, root in [
            ("a_alpha", "alpha.zip", "/root-a/alpha.zip", 1),
            ("a_bravo", "bravo.zip", "/root-a/bravo.zip", 1),
            ("a_charlie", "charlie.zip", "/root-a/charlie.zip", 1),
            ("b_alpha", "alpha.zip", "/root-b/alpha.zip", 2),
            ("b_bravo", "bravo.zip", "/root-b/bravo.zip", 2),
            ("b_charlie", "charlie.zip", "/root-b/charlie.zip", 2),
        ]:
            index.add(Resource(
                id=rid, name=name, path=path, parent_id=None,
                content_type="software", root_mapping_id=root,
                extension="zip", mime_type="application/zip",
                size=100, thumbnail="", status="active",
            ))
        await index.commit()

    return state_engine, index_engine, token


def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://testserver")


async def test_disabled_root_resources_never_appear_as_siblings(monkeypatch):
    """Disabled root resources must not leak into related/previous/next."""
    state_engine, index_engine, token = await _build_store(monkeypatch, second_root_enabled=False)
    async with _client() as client:
        resp = await client.get("/api/resources/a_bravo", cookies={USER_SESSION_COOKIE: token})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    related_ids = {r["id"] for r in data["related"]}
    prev_id = data["previous"]["id"] if data["previous"] else None
    next_id = data["next"]["id"] if data["next"] else None
    leaked = related_ids | {prev_id, next_id}
    assert "b_alpha" not in leaked
    assert "b_bravo" not in leaked
    assert "b_charlie" not in leaked
    assert related_ids <= {"a_alpha", "a_charlie"}
    await state_engine.dispose()
    await index_engine.dispose()


async def test_enabled_roots_with_colliding_parent_id_do_not_mix(monkeypatch):
    """Two enabled roots sharing parent_id must keep siblings per-root."""
    state_engine, index_engine, token = await _build_store(monkeypatch, second_root_enabled=True)
    async with _client() as client:
        resp_a = await client.get("/api/resources/a_bravo", cookies={USER_SESSION_COOKIE: token})
        resp_b = await client.get("/api/resources/b_bravo", cookies={USER_SESSION_COOKIE: token})
    assert resp_a.status_code == 200, resp_a.text
    assert resp_b.status_code == 200, resp_b.text
    data_a = resp_a.json()
    data_b = resp_b.json()

    related_a = {r["id"] for r in data_a["related"]}
    related_b = {r["id"] for r in data_b["related"]}
    assert related_a == {"a_alpha", "a_charlie"}, related_a
    assert related_b == {"b_alpha", "b_charlie"}, related_b

    prev_a = data_a["previous"]["id"] if data_a["previous"] else None
    next_a = data_a["next"]["id"] if data_a["next"] else None
    prev_b = data_b["previous"]["id"] if data_b["previous"] else None
    next_b = data_b["next"]["id"] if data_b["next"] else None
    assert prev_a in (None, "a_alpha")
    assert next_a in (None, "a_charlie")
    assert prev_b in (None, "b_alpha")
    assert next_b in (None, "b_charlie")
    await state_engine.dispose()
    await index_engine.dispose()


async def test_main_resource_still_returned_for_enabled_root(monkeypatch):
    """Main resource detail shape is preserved for an enabled-root resource."""
    state_engine, index_engine, token = await _build_store(monkeypatch, second_root_enabled=False)
    async with _client() as client:
        resp = await client.get("/api/resources/a_alpha", cookies={USER_SESSION_COOKIE: token})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["id"] == "a_alpha"
    assert "related" in data and isinstance(data["related"], list)
    assert "previous" in data and "next" in data
    assert "breadcrumbs" in data and "capabilities" in data
    await state_engine.dispose()
    await index_engine.dispose()
