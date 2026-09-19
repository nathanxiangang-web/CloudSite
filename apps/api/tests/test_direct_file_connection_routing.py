"""Focused route tests for direct file connection routing (X1 follow-up).

Proves that /d/{resource_id}, /p/{resource_id}, and the Office/PDF/text preview
endpoints resolve the AList connection from resource.root_mapping_id through
ContentRootMapping.connection_id instead of hardcoding connection id=1.

Covers:
- A resource indexed under connection 2 uses connection 2 for download, preview,
  Office preview, PDF preview, and text preview.
- A known enabled mapping whose connection is disabled fails closed (no fallback
  to connection 1) for download and preview.
- A known enabled mapping whose connection is missing fails closed for download.
- A disabled mapping fails closed for download and preview (publication scope).
- A connection-1 resource still uses connection 1 (legacy behavior preserved).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import auth, main
from cloudsite.database import IndexBase, StateBase
from cloudsite.download import DownloadError, DownloadResolution
from cloudsite.download_rate_limit import DownloadRateDecision
from cloudsite.models import (
    AListConnection,
    ContentRootMapping,
    Resource,
    SystemSetting,
    User,
    utcnow,
)
from cloudsite.office import OfficePreviewError
from cloudsite.preview import PreviewError, PreviewResolution
from cloudsite.sessions import USER_SESSION_COOKIE, create_user_session


async def _bootstrap(tmp_path):
    state_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    index_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)
    state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    index_factory = async_sessionmaker(index_engine, expire_on_commit=False)
    return state_engine, index_engine, state_factory, index_factory


def _patch_sessions(monkeypatch, state_factory, index_factory):
    monkeypatch.setattr(main, "StateSession", state_factory)
    monkeypatch.setattr(main, "IndexSession", index_factory)
    monkeypatch.setattr(auth, "StateSession", state_factory)


async def _seed(tmp_path, monkeypatch):
    state_engine, index_engine, state_factory, index_factory = await _bootstrap(tmp_path)
    _patch_sessions(monkeypatch, state_factory, index_factory)

    async with state_factory() as state:
        state.add(SystemSetting(key="setup_completed", value="true", value_type="string"))
        state.add(AListConnection(
            id=1, name="conn-one", base_url="http://alist1.example",
            base_path="/", username="u", password_ciphertext="", enabled=True,
        ))
        state.add(AListConnection(
            id=2, name="conn-two", base_url="http://alist2.example",
            base_path="/", username="u", password_ciphertext="", enabled=True,
        ))
        state.add(AListConnection(
            id=5, name="conn-disabled", base_url="http://alist5.example",
            base_path="/", username="u", password_ciphertext="", enabled=False,
        ))
        state.add(ContentRootMapping(
            id=1, connection_id=1, content_type="software", display_name="Software",
            alist_path="/software", enabled=True,
        ))
        state.add(ContentRootMapping(
            id=2, connection_id=2, content_type="video", display_name="Video",
            alist_path="/video", enabled=True,
        ))
        state.add(ContentRootMapping(
            id=4, connection_id=5, content_type="archive", display_name="Archive",
            alist_path="/archive", enabled=True,
        ))
        state.add(ContentRootMapping(
            id=6, connection_id=7, content_type="docs", display_name="Docs",
            alist_path="/docs", enabled=True,
        ))
        state.add(ContentRootMapping(
            id=3, connection_id=1, content_type="legacy", display_name="Legacy",
            alist_path="/legacy", enabled=False,
        ))
        user = User(
            username="reader", username_normalized="reader", password_hash="x",
            status="active", created_at=utcnow(), updated_at=utcnow(),
        )
        state.add(user)
        await state.flush()
        _, user_token = await create_user_session(state, user.id, utcnow())
        await state.commit()

    now = datetime.now(timezone.utc)
    async with index_factory() as index:
        index.add(Resource(
            id="r-conn1-zip", name="conn1.zip", path="/software/conn1.zip",
            parent_id=None, content_type="software", root_mapping_id=1,
            extension="zip", mime_type="application/zip", size=10, status="active",
            indexed_at=now,
        ))
        index.add(Resource(
            id="r-conn2-zip", name="conn2.zip", path="/video/conn2.zip",
            parent_id=None, content_type="video", root_mapping_id=2,
            extension="zip", mime_type="application/zip", size=10, status="active",
            indexed_at=now,
        ))
        index.add(Resource(
            id="r-conn2-docx", name="conn2.docx", path="/video/conn2.docx",
            parent_id=None, content_type="video", root_mapping_id=2,
            extension="docx",
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            size=10, status="active", indexed_at=now,
        ))
        index.add(Resource(
            id="r-conn2-pdf", name="conn2.pdf", path="/video/conn2.pdf",
            parent_id=None, content_type="video", root_mapping_id=2,
            extension="pdf", mime_type="application/pdf", size=10, status="active",
            indexed_at=now,
        ))
        index.add(Resource(
            id="r-conn2-txt", name="conn2.txt", path="/video/conn2.txt",
            parent_id=None, content_type="video", root_mapping_id=2,
            extension="txt", mime_type="text/plain", size=10, status="active",
            indexed_at=now,
        ))
        index.add(Resource(
            id="r-disabled-conn", name="disabled-conn.zip", path="/archive/disabled-conn.zip",
            parent_id=None, content_type="archive", root_mapping_id=4,
            extension="zip", mime_type="application/zip", size=10, status="active",
            indexed_at=now,
        ))
        index.add(Resource(
            id="r-missing-conn", name="missing-conn.zip", path="/docs/missing-conn.zip",
            parent_id=None, content_type="docs", root_mapping_id=6,
            extension="zip", mime_type="application/zip", size=10, status="active",
            indexed_at=now,
        ))
        index.add(Resource(
            id="r-disabled-mapping", name="disabled-mapping.zip", path="/legacy/disabled-mapping.zip",
            parent_id=None, content_type="legacy", root_mapping_id=3,
            extension="zip", mime_type="application/zip", size=10, status="active",
            indexed_at=now,
        ))
        await index.commit()

    return {
        "state_engine": state_engine,
        "index_engine": index_engine,
        "state_factory": state_factory,
        "index_factory": index_factory,
        "user_token": user_token,
    }


def _install_resolvers(monkeypatch, captured):
    class FakeRuntime:
        connection_ids = {1: 1, 2: 2, 4: 5, 6: None}
        enabled_roots = {1, 2}

        def connection_id_for(self, root_mapping_id):
            return self.connection_ids.get(root_mapping_id)

        def require_enabled(self, root_mapping_id):
            if root_mapping_id not in self.enabled_roots:
                raise PreviewError("PV-005", "upstream unavailable", 503)

    runtime = FakeRuntime()

    async def _fake_download(resource, connection):
        captured["download_connection_id"] = getattr(connection, "id", None)
        if not connection or not connection.enabled:
            raise DownloadError("DL-002", "AList not configured", "alist_connection", 503)
        return DownloadResolution(
            url=f"https://download.example/conn{connection.id}/{resource.id}",
            target_host="download.example", base_path="/", has_sign=True, steps=[],
        )

    async def _fake_preview(resource, provider_runtime, force_refresh=False):
        connection_id = provider_runtime.connection_id_for(resource.root_mapping_id)
        captured["preview_connection_id"] = connection_id
        provider_runtime.require_enabled(resource.root_mapping_id)
        return PreviewResolution(
            url=f"https://preview.example/conn{connection_id}/{resource.id}",
            target_host="preview.example", cache_hit=False,
        )

    async def _fake_ensure_cached(resource, provider_runtime):
        connection_id = provider_runtime.connection_id_for(resource.root_mapping_id)
        captured["office_connection_id"] = connection_id
        provider_runtime.require_enabled(resource.root_mapping_id)
        return Path(f"/tmp/fake-office-{resource.id}")

    async def _fake_text_preview(resource, provider_runtime):
        connection_id = provider_runtime.connection_id_for(resource.root_mapping_id)
        captured["text_connection_id"] = connection_id
        provider_runtime.require_enabled(resource.root_mapping_id)
        return {
            "content": f"conn{connection_id}:{resource.id}",
            "truncated": False,
            "size": resource.size,
            "encoding": "utf-8",
            "preview_type": "text",
        }

    async def _fake_rate(address, now=None):
        return DownloadRateDecision(allowed=True)

    monkeypatch.setattr("cloudsite.routers.downloads.resolve_download_entry", _fake_download)
    monkeypatch.setattr("cloudsite.routers.downloads.check_download_rate", _fake_rate)
    monkeypatch.setattr("cloudsite.routers.previews.provider_runtime", lambda _state: runtime)
    monkeypatch.setattr("cloudsite.routers.resources.provider_runtime", lambda _state: runtime)
    monkeypatch.setattr("cloudsite.routers.previews.resolve_preview_url", _fake_preview)
    monkeypatch.setattr("cloudsite.routers.resources.ensure_preview_cached", _fake_ensure_cached)
    monkeypatch.setattr("cloudsite.routers.resources.load_text_preview", _fake_text_preview)


def _authed_client(transport, user_token):
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    client.cookies.set(USER_SESSION_COOKIE, user_token)
    return client


async def test_download_uses_connection_two_for_connection_two_resource(tmp_path, monkeypatch):
    ctx = await _seed(tmp_path, monkeypatch)
    captured: dict = {}
    _install_resolvers(monkeypatch, captured)
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with _authed_client(transport, ctx["user_token"]) as client:
            resp = await client.get("/d/r-conn2-zip", follow_redirects=False)
            assert resp.status_code == 302, resp.text
            assert resp.headers["location"] == "https://download.example/conn2/r-conn2-zip"
        assert captured["download_connection_id"] == 2
    finally:
        await ctx["state_engine"].dispose()
        await ctx["index_engine"].dispose()


async def test_preview_uses_connection_two_for_connection_two_resource(tmp_path, monkeypatch):
    ctx = await _seed(tmp_path, monkeypatch)
    captured: dict = {}
    _install_resolvers(monkeypatch, captured)
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with _authed_client(transport, ctx["user_token"]) as client:
            resp = await client.get("/p/r-conn2-zip", follow_redirects=False)
            assert resp.status_code == 302, resp.text
            assert resp.headers["location"] == "https://preview.example/conn2/r-conn2-zip"
        assert captured["preview_connection_id"] == 2
    finally:
        await ctx["state_engine"].dispose()
        await ctx["index_engine"].dispose()


async def test_office_preview_uses_connection_two(tmp_path, monkeypatch):
    ctx = await _seed(tmp_path, monkeypatch)
    captured: dict = {}
    _install_resolvers(monkeypatch, captured)
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with _authed_client(transport, ctx["user_token"]) as client:
            resp = await client.get("/api/resources/r-conn2-docx/office-preview")
            assert resp.status_code == 200, resp.text
            assert resp.json()["url"].startswith("/office-files/r-conn2-docx.docx?ticket=")
        assert captured["office_connection_id"] == 2
    finally:
        await ctx["state_engine"].dispose()
        await ctx["index_engine"].dispose()


async def test_pdf_preview_uses_connection_two(tmp_path, monkeypatch):
    ctx = await _seed(tmp_path, monkeypatch)
    captured: dict = {}
    _install_resolvers(monkeypatch, captured)
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with _authed_client(transport, ctx["user_token"]) as client:
            resp = await client.get("/api/resources/r-conn2-pdf/pdf-preview")
            assert resp.status_code == 200, resp.text
            assert resp.json()["url"].startswith("/office-files/r-conn2-pdf.pdf?ticket=")
        assert captured["office_connection_id"] == 2
    finally:
        await ctx["state_engine"].dispose()
        await ctx["index_engine"].dispose()


async def test_text_preview_uses_connection_two(tmp_path, monkeypatch):
    ctx = await _seed(tmp_path, monkeypatch)
    captured: dict = {}
    _install_resolvers(monkeypatch, captured)
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with _authed_client(transport, ctx["user_token"]) as client:
            resp = await client.get("/api/resources/r-conn2-txt/text-preview")
            assert resp.status_code == 200, resp.text
            assert resp.json()["content"] == "conn2:r-conn2-txt"
        assert captured["text_connection_id"] == 2
    finally:
        await ctx["state_engine"].dispose()
        await ctx["index_engine"].dispose()


async def test_download_connection_one_resource_still_uses_connection_one(tmp_path, monkeypatch):
    ctx = await _seed(tmp_path, monkeypatch)
    captured: dict = {}
    _install_resolvers(monkeypatch, captured)
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with _authed_client(transport, ctx["user_token"]) as client:
            resp = await client.get("/d/r-conn1-zip", follow_redirects=False)
            assert resp.status_code == 302, resp.text
            assert resp.headers["location"] == "https://download.example/conn1/r-conn1-zip"
        assert captured["download_connection_id"] == 1
    finally:
        await ctx["state_engine"].dispose()
        await ctx["index_engine"].dispose()


async def test_download_fails_closed_when_connection_disabled(tmp_path, monkeypatch):
    ctx = await _seed(tmp_path, monkeypatch)
    captured: dict = {}
    _install_resolvers(monkeypatch, captured)
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with _authed_client(transport, ctx["user_token"]) as client:
            resp = await client.get("/d/r-disabled-conn", follow_redirects=False)
            assert resp.status_code == 302, resp.text
            assert "download-error" in resp.headers["location"]
            assert "DL-002" in resp.headers["location"]
        assert captured["download_connection_id"] == 5
    finally:
        await ctx["state_engine"].dispose()
        await ctx["index_engine"].dispose()


async def test_preview_fails_closed_when_connection_disabled(tmp_path, monkeypatch):
    ctx = await _seed(tmp_path, monkeypatch)
    captured: dict = {}
    _install_resolvers(monkeypatch, captured)
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with _authed_client(transport, ctx["user_token"]) as client:
            resp = await client.get("/p/r-disabled-conn", follow_redirects=False)
            assert resp.status_code == 302, resp.text
            assert "preview_error" in resp.headers["location"]
            assert "PV-005" in resp.headers["location"]
        assert captured["preview_connection_id"] == 5
    finally:
        await ctx["state_engine"].dispose()
        await ctx["index_engine"].dispose()


async def test_download_fails_closed_when_connection_missing(tmp_path, monkeypatch):
    ctx = await _seed(tmp_path, monkeypatch)
    captured: dict = {}
    _install_resolvers(monkeypatch, captured)
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with _authed_client(transport, ctx["user_token"]) as client:
            resp = await client.get("/d/r-missing-conn", follow_redirects=False)
            assert resp.status_code == 302, resp.text
            assert "download-error" in resp.headers["location"]
            assert "DL-002" in resp.headers["location"]
        assert captured["download_connection_id"] is None
    finally:
        await ctx["state_engine"].dispose()
        await ctx["index_engine"].dispose()


async def test_download_fails_closed_when_mapping_disabled(tmp_path, monkeypatch):
    ctx = await _seed(tmp_path, monkeypatch)
    captured: dict = {}
    _install_resolvers(monkeypatch, captured)
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with _authed_client(transport, ctx["user_token"]) as client:
            resp = await client.get("/d/r-disabled-mapping", follow_redirects=False)
            assert resp.status_code == 302, resp.text
            assert "download-error" in resp.headers["location"]
            assert "RESOURCE_NOT_AVAILABLE" in resp.headers["location"]
        assert "download_connection_id" not in captured
    finally:
        await ctx["state_engine"].dispose()
        await ctx["index_engine"].dispose()


async def test_preview_fails_closed_when_mapping_disabled(tmp_path, monkeypatch):
    ctx = await _seed(tmp_path, monkeypatch)
    captured: dict = {}
    _install_resolvers(monkeypatch, captured)
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with _authed_client(transport, ctx["user_token"]) as client:
            resp = await client.get("/p/r-disabled-mapping", follow_redirects=False)
            assert resp.status_code == 302, resp.text
            assert "preview_error" in resp.headers["location"]
            assert "PV-001" in resp.headers["location"]
        assert "preview_connection_id" not in captured
    finally:
        await ctx["state_engine"].dispose()
        await ctx["index_engine"].dispose()
