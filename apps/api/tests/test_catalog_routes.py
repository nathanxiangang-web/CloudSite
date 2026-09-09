"""C1 Catalog HTTP module: route registration, schema alignment, and behavior checks.

These tests verify the Catalog HTTP contract against the reviewed C1 model
contract (string stable IDs, draft suppression, no arbitrary URLs). The
parallel-developed services/catalog.py is not present in this baseline, so the
service module is injected via sys.modules with monkeypatched named functions.
The integrated runtime check (real service + real database) is deferred to the
verification phase.
"""
import sys
import types
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import auth, main
from cloudsite.catalog_schemas import (
    CatalogEntryCreateInput,
    CatalogEntryDetail,
    CatalogEntryListOutput,
    CatalogEntryNotFound,
    CatalogEntryNotPreviewable,
    CatalogEntrySummary,
    CatalogEntryUpdateInput,
    CatalogLocationBindInput,
    CatalogLocationSummary,
    CatalogLocationUnavailable,
    CatalogPreviewOutput,
    CatalogRevisionConflict,
)
from cloudsite.database import StateBase
from cloudsite.models import SiteSettings, SystemSetting, User, utcnow
from cloudsite.sessions import USER_SESSION_COOKIE, create_user_session


# ---- Helpers ----

def _iter_routes(source):
    for route in getattr(source, "routes", []):
        original = getattr(route, "original_router", None)
        if original is not None and not hasattr(route, "path"):
            yield from _iter_routes(original)
            continue
        yield route


def _catalog_endpoints():
    endpoints = []
    for route in _iter_routes(main.app):
        path = getattr(route, "path", "")
        if "catalog" not in path:
            continue
        methods = getattr(route, "methods", None) or set()
        for method in sorted(methods):
            if method in ("HEAD", "OPTIONS"):
                continue
            endpoints.append((method, path, route))
    return endpoints


def _entry_id() -> str:
    return "ce_" + "a" * 32


def _asset_id() -> str:
    return "ca_" + "b" * 32


def _resource_id() -> str:
    return "r_" + "c" * 32


def _location_id() -> str:
    return "cl_" + "d" * 32


def _make_entry_summary(entry_id=None, status="published", revision=1):
    return CatalogEntrySummary(
        entry_id=entry_id or _entry_id(),
        title="Test Entry",
        summary="A test catalog entry",
        content_type="software",
        status=status,
        revision=revision,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc) if status == "published" else None,
    )


def _make_entry_detail(entry_id=None, status="published", revision=1):
    base = _make_entry_summary(entry_id, status, revision)
    return CatalogEntryDetail(
        **base.model_dump(),
        description="Full description",
        locations=[],
    )


def _make_location_summary():
    return CatalogLocationSummary(
        location_id=_location_id(),
        asset_id=_asset_id(),
        display_name="test.iso",
        sort_order=0,
        available=True,
        content_type="application/octet-stream",
        extension="iso",
        size=1024,
    )


def _make_list_output(items=None, total=None):
    items = items or [_make_entry_summary()]
    total = total if total is not None else len(items)
    return CatalogEntryListOutput(
        items=items,
        page=1,
        page_size=20,
        total=total,
        total_pages=max(1, (total + 19) // 20),
    )


def _make_preview_output():
    return CatalogPreviewOutput(
        entry=_make_entry_detail(),
        previewable=True,
        reason="",
    )


def _install_fake_catalog_service(monkeypatch, **overrides):
    """Inject a fake services.catalog module with the agreed named functions."""
    fake_module = types.ModuleType("cloudsite.services.catalog")
    defaults = {
        "create_catalog_entry": AsyncMock(return_value=_make_entry_detail()),
        "get_catalog_entry": AsyncMock(return_value=_make_entry_detail()),
        "list_catalog_entries": AsyncMock(return_value=_make_list_output()),
        "update_catalog_entry": AsyncMock(return_value=_make_entry_detail()),
        "attach_catalog_location": AsyncMock(return_value=_make_location_summary()),
        "validate_catalog_entry_for_preview": AsyncMock(return_value=_make_preview_output()),
        "publish_catalog_entry": AsyncMock(return_value=_make_entry_detail()),
    }
    defaults.update(overrides)
    for name, value in defaults.items():
        setattr(fake_module, name, value)
    monkeypatch.setitem(sys.modules, "cloudsite.services.catalog", fake_module)
    return fake_module


async def _setup_client(monkeypatch, admin=False, user=False):
    """Create a test client with optional admin or user authentication."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    user_token = None
    async with factory() as session:
        session.add(SiteSettings(id=1))
        session.add(SystemSetting(key="setup_completed", value="true", value_type="string"))
        if user:
            user_obj = User(
                username="user",
                username_normalized="user",
                password_hash="x",
                status="active",
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            session.add(user_obj)
            await session.flush()
            _, user_token = await create_user_session(session, user_obj.id, utcnow())
        await session.commit()
    monkeypatch.setattr(main, "StateSession", factory)
    monkeypatch.setattr(auth, "StateSession", factory)
    monkeypatch.setattr(main, "IndexSession", factory)
    transport = httpx.ASGITransport(app=main.app)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    if admin:
        client.cookies.set(main.SESSION_COOKIE, main.create_session_token("admin"))
    if user and user_token:
        client.cookies.set(USER_SESSION_COOKIE, user_token)
    return client, engine


# ---- Route registration tests ----

def test_catalog_routes_registered():
    """All required Catalog routes are registered with correct paths and methods."""
    endpoints = _catalog_endpoints()
    path_methods = {}
    for method, path, _ in endpoints:
        path_methods.setdefault(path, set()).add(method)
    expected = {
        "/api/catalog": {"GET"},
        "/api/catalog/{entry_id}": {"GET"},
        "/api/admin/catalog": {"GET", "POST"},
        "/api/admin/catalog/{entry_id}": {"GET", "PUT"},
        "/api/admin/catalog/{entry_id}/locations": {"POST"},
        "/api/admin/catalog/{entry_id}/preview": {"POST"},
        "/api/admin/catalog/{entry_id}/publish": {"POST"},
    }
    for path, methods in expected.items():
        assert path in path_methods, f"missing route {path}"
        assert path_methods[path] == methods, (
            f"route {path}: expected {methods}, got {path_methods[path]}"
        )


def test_catalog_entry_id_path_param_is_str():
    """entry_id path parameters must be str (reviewed C1 stable-ID contract)."""
    import inspect
    from cloudsite.routers.admin.catalog import (
        admin_catalog_bind_location,
        admin_catalog_detail,
        admin_catalog_preview,
        admin_catalog_publish,
        admin_catalog_update,
    )
    from cloudsite.routers.catalog import public_catalog_detail

    for func in [
        public_catalog_detail,
        admin_catalog_detail,
        admin_catalog_update,
        admin_catalog_bind_location,
        admin_catalog_preview,
        admin_catalog_publish,
    ]:
        sig = inspect.signature(func)
        param = sig.parameters["entry_id"]
        assert param.annotation is str, (
            f"{func.__name__}: entry_id must be str, got {param.annotation}"
        )


def test_catalog_response_models_declared():
    """Routes declare response_model aligned with the schema contract."""
    from cloudsite.routers.admin.catalog import router as admin_router
    from cloudsite.routers.catalog import router as public_router

    expected = {
        ("/api/admin/catalog", "GET"): CatalogEntryListOutput,
        ("/api/admin/catalog/{entry_id}", "GET"): CatalogEntryDetail,
        ("/api/admin/catalog", "POST"): CatalogEntryDetail,
        ("/api/admin/catalog/{entry_id}", "PUT"): CatalogEntryDetail,
        ("/api/admin/catalog/{entry_id}/locations", "POST"): CatalogLocationSummary,
        ("/api/admin/catalog/{entry_id}/preview", "POST"): CatalogPreviewOutput,
        ("/api/admin/catalog/{entry_id}/publish", "POST"): CatalogEntryDetail,
        ("/api/catalog", "GET"): CatalogEntryListOutput,
        ("/api/catalog/{entry_id}", "GET"): CatalogEntryDetail,
    }
    for router in [admin_router, public_router]:
        for route in router.routes:
            key = (route.path, sorted(route.methods or set())[0])
            if key in expected:
                assert route.response_model is expected[key], (
                    f"{key}: expected {expected[key]}, got {route.response_model}"
                )


# ---- Schema alignment tests ----

def test_entry_summary_uses_str_entry_id():
    """CatalogEntrySummary.entry_id is str, not int (model contract alignment)."""
    fields = CatalogEntrySummary.model_fields
    assert "entry_id" in fields
    assert "id" not in fields


def test_location_summary_uses_str_location_id():
    """CatalogLocationSummary.location_id is str, not int."""
    fields = CatalogLocationSummary.model_fields
    assert "location_id" in fields
    assert "id" not in fields


def test_bind_input_requires_resource_id_not_url():
    """CatalogLocationBindInput requires resource_id and rejects arbitrary URLs."""
    fields = CatalogLocationBindInput.model_fields
    assert "resource_id" in fields
    assert "url" not in fields
    assert "upstream_url" not in fields
    assert "mirror_url" not in fields
    valid = CatalogLocationBindInput(
        asset_id=_asset_id(),
        resource_id=_resource_id(),
    )
    assert valid.resource_id == _resource_id()
    with pytest.raises(Exception):
        CatalogLocationBindInput(asset_id=_asset_id(), resource_id="not-a-valid-id")
    with pytest.raises(Exception):
        CatalogLocationBindInput(asset_id="bad", resource_id=_resource_id())


def test_bind_input_rejects_arbitrary_url_fields():
    """Extra URL fields are not accepted by the bind input (extra=forbid)."""
    with pytest.raises(Exception):
        CatalogLocationBindInput(
            asset_id=_asset_id(),
            resource_id=_resource_id(),
            upstream_url="https://evil.example/file.iso",
        )


# ---- Admin route behavior tests (monkeypatched service) ----

async def test_admin_list_calls_list_catalog_entries(monkeypatch):
    """Admin list calls list_catalog_entries with published_only=False."""
    fake = _install_fake_catalog_service(monkeypatch)
    client, engine = await _setup_client(monkeypatch, admin=True)
    async with client:
        response = await client.get("/api/admin/catalog")
        assert response.status_code == 200
        assert "items" in response.json()
        fake.list_catalog_entries.assert_called_once()
        call_kwargs = fake.list_catalog_entries.call_args.kwargs
        assert call_kwargs["published_only"] is False
    await engine.dispose()


async def test_admin_detail_calls_get_catalog_entry(monkeypatch):
    """Admin detail calls get_catalog_entry without published_only restriction."""
    fake = _install_fake_catalog_service(monkeypatch)
    client, engine = await _setup_client(monkeypatch, admin=True)
    async with client:
        response = await client.get(f"/api/admin/catalog/{_entry_id()}")
        assert response.status_code == 200
        fake.get_catalog_entry.assert_called_once()
        call_args = fake.get_catalog_entry.call_args
        assert call_args.args[2] == _entry_id()


async def test_admin_create_calls_create_catalog_entry(monkeypatch):
    """Admin create calls create_catalog_entry with the validated payload."""
    fake = _install_fake_catalog_service(monkeypatch)
    client, engine = await _setup_client(monkeypatch, admin=True)
    async with client:
        response = await client.post(
            "/api/admin/catalog",
            json={"title": "New Entry", "content_type": "software"},
        )
        assert response.status_code == 201
        fake.create_catalog_entry.assert_called_once()


async def test_admin_update_calls_update_catalog_entry(monkeypatch):
    """Admin update calls update_catalog_entry with entry_id and payload."""
    fake = _install_fake_catalog_service(monkeypatch)
    client, engine = await _setup_client(monkeypatch, admin=True)
    async with client:
        response = await client.put(
            f"/api/admin/catalog/{_entry_id()}",
            json={"expected_revision": 1, "title": "Updated"},
        )
        assert response.status_code == 200
        fake.update_catalog_entry.assert_called_once()
        call_args = fake.update_catalog_entry.call_args
        assert call_args.args[2] == _entry_id()


async def test_admin_bind_calls_attach_catalog_location(monkeypatch):
    """Admin bind calls attach_catalog_location with resource_id, not URLs."""
    fake = _install_fake_catalog_service(monkeypatch)
    client, engine = await _setup_client(monkeypatch, admin=True)
    async with client:
        response = await client.post(
            f"/api/admin/catalog/{_entry_id()}/locations",
            json={"asset_id": _asset_id(), "resource_id": _resource_id()},
        )
        assert response.status_code == 201
        fake.attach_catalog_location.assert_called_once()


async def test_admin_preview_calls_validate_for_preview(monkeypatch):
    """Admin preview calls validate_catalog_entry_for_preview."""
    fake = _install_fake_catalog_service(monkeypatch)
    client, engine = await _setup_client(monkeypatch, admin=True)
    async with client:
        response = await client.post(f"/api/admin/catalog/{_entry_id()}/preview")
        assert response.status_code == 200
        fake.validate_catalog_entry_for_preview.assert_called_once()


async def test_admin_publish_calls_publish_catalog_entry(monkeypatch):
    """Admin publish calls publish_catalog_entry."""
    fake = _install_fake_catalog_service(monkeypatch)
    client, engine = await _setup_client(monkeypatch, admin=True)
    async with client:
        response = await client.post(f"/api/admin/catalog/{_entry_id()}/publish")
        assert response.status_code == 200
        fake.publish_catalog_entry.assert_called_once()


async def test_admin_create_translates_not_found_to_404(monkeypatch):
    """CatalogEntryNotFound is translated to 404."""
    _install_fake_catalog_service(
        monkeypatch,
        create_catalog_entry=AsyncMock(side_effect=CatalogEntryNotFound()),
    )
    client, engine = await _setup_client(monkeypatch, admin=True)
    async with client:
        response = await client.post(
            "/api/admin/catalog",
            json={"title": "X", "content_type": "software"},
        )
        assert response.status_code == 404


async def test_admin_update_translates_revision_conflict_to_409(monkeypatch):
    """CatalogRevisionConflict is translated to 409."""
    _install_fake_catalog_service(
        monkeypatch,
        update_catalog_entry=AsyncMock(side_effect=CatalogRevisionConflict()),
    )
    client, engine = await _setup_client(monkeypatch, admin=True)
    async with client:
        response = await client.put(
            f"/api/admin/catalog/{_entry_id()}",
            json={"expected_revision": 5, "title": "X"},
        )
        assert response.status_code == 409


async def test_admin_bind_translates_location_unavailable_to_409(monkeypatch):
    """CatalogLocationUnavailable is translated to 409."""
    _install_fake_catalog_service(
        monkeypatch,
        attach_catalog_location=AsyncMock(side_effect=CatalogLocationUnavailable()),
    )
    client, engine = await _setup_client(monkeypatch, admin=True)
    async with client:
        response = await client.post(
            f"/api/admin/catalog/{_entry_id()}/locations",
            json={"asset_id": _asset_id(), "resource_id": _resource_id()},
        )
        assert response.status_code == 409


async def test_admin_preview_translates_not_previewable_to_409(monkeypatch):
    """CatalogEntryNotPreviewable is translated to 409."""
    _install_fake_catalog_service(
        monkeypatch,
        validate_catalog_entry_for_preview=AsyncMock(side_effect=CatalogEntryNotPreviewable()),
    )
    client, engine = await _setup_client(monkeypatch, admin=True)
    async with client:
        response = await client.post(f"/api/admin/catalog/{_entry_id()}/preview")
        assert response.status_code == 409


# ---- Public route behavior tests (draft suppression) ----

async def test_public_list_calls_with_published_only_true(monkeypatch):
    """Public list calls list_catalog_entries with published_only=True."""
    fake = _install_fake_catalog_service(monkeypatch)
    client, engine = await _setup_client(monkeypatch, user=True)
    async with client:
        response = await client.get("/api/catalog")
        assert response.status_code == 200
        call_kwargs = fake.list_catalog_entries.call_args.kwargs
        assert call_kwargs["published_only"] is True


async def test_public_detail_calls_with_published_only_true(monkeypatch):
    """Public detail calls get_catalog_entry with published_only=True."""
    fake = _install_fake_catalog_service(monkeypatch)
    client, engine = await _setup_client(monkeypatch, user=True)
    async with client:
        response = await client.get(f"/api/catalog/{_entry_id()}")
        assert response.status_code == 200
        call_kwargs = fake.get_catalog_entry.call_args.kwargs
        assert call_kwargs["published_only"] is True


async def test_public_detail_returns_404_for_missing_entry(monkeypatch):
    """Public detail returns 404 when service returns None (draft or missing)."""
    _install_fake_catalog_service(
        monkeypatch,
        get_catalog_entry=AsyncMock(return_value=None),
    )
    client, engine = await _setup_client(monkeypatch, user=True)
    async with client:
        response = await client.get(f"/api/catalog/{_entry_id()}")
        assert response.status_code == 404


async def test_public_detail_translates_not_found_to_404(monkeypatch):
    """CatalogEntryNotFound from service is translated to 404 for public detail."""
    _install_fake_catalog_service(
        monkeypatch,
        get_catalog_entry=AsyncMock(side_effect=CatalogEntryNotFound()),
    )
    client, engine = await _setup_client(monkeypatch, user=True)
    async with client:
        response = await client.get(f"/api/catalog/{_entry_id()}")
        assert response.status_code == 404


# ---- Admin auth boundary tests ----

async def test_admin_catalog_rejects_anonymous(monkeypatch):
    """Admin catalog routes reject anonymous requests with 403."""
    _install_fake_catalog_service(monkeypatch)
    client, engine = await _setup_client(monkeypatch, admin=False)
    async with client:
        response = await client.get("/api/admin/catalog")
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "ADMIN_REQUIRED"
    await engine.dispose()


async def test_admin_catalog_create_rejects_anonymous(monkeypatch):
    """Admin catalog create rejects anonymous requests with 403."""
    _install_fake_catalog_service(monkeypatch)
    client, engine = await _setup_client(monkeypatch, admin=False)
    async with client:
        response = await client.post(
            "/api/admin/catalog",
            json={"title": "X", "content_type": "software"},
        )
        assert response.status_code == 403
    await engine.dispose()
