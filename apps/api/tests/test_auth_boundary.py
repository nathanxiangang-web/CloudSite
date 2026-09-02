from datetime import timedelta

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import auth, main, site_assets
from cloudsite.database import StateBase
from cloudsite.models import AListConnection, User, utcnow
from cloudsite.preview import PREVIEW_TICKET_TTL_SECONDS, create_preview_ticket
from cloudsite.sessions import USER_SESSION_COOKIE, create_user_session


async def boundary_client(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)
    monkeypatch.setattr(main, "StateSession", factory)
    monkeypatch.setattr(auth, "StateSession", factory)
    transport = httpx.ASGITransport(app=main.app)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    return client, factory, engine


async def test_anonymous_whitelist_and_protected_api(monkeypatch):
    client, _, engine = await boundary_client(monkeypatch)
    async def must_not_run(*_args, **_kwargs):
        raise AssertionError("anonymous download reached rate limiter")
    monkeypatch.setattr(main, "check_download_rate", must_not_run)
    async with client:
        health = await client.get("/api/health")
        assert health.status_code == 200
        protected = await client.get("/api/home")
        assert protected.status_code == 401
        assert protected.json()["detail"]["code"] == "AUTH_REQUIRED"
        preview = await client.get("/p/not-a-resource")
        assert preview.status_code == 401
        assert preview.json()["detail"]["code"] == "AUTH_REQUIRED"
        download = await client.get("/d/not-a-resource")
        assert download.status_code == 401
        assert download.json()["detail"]["code"] == "AUTH_REQUIRED"
        share = await client.get("/api/shares/not-a-share")
        assert share.status_code == 401
        assert share.json()["detail"]["code"] == "AUTH_REQUIRED"
        public_share = await client.get("/api/public/shares/not-a-share")
        assert public_share.status_code == 404
        assert public_share.json()["detail"]["code"] == "SHARE_NOT_FOUND"
        share_page = await client.get("/api/public/share-page")
        assert share_page.status_code == 200
        assert share_page.json() == {"site_name": "CloudSite", "share_image_url": ""}
        short_share = await client.get("/s/not-a-share", follow_redirects=False)
        assert short_share.status_code == 404
        assert short_share.json()["detail"]["code"] == "SHARE_NOT_FOUND"
        admin = await client.get("/api/admin/users")
        assert admin.status_code == 403
        assert admin.json()["detail"]["code"] == "ADMIN_REQUIRED"
    await engine.dispose()


async def test_share_page_image_upload_public_read_and_remove(monkeypatch, tmp_path):
    client, _, engine = await boundary_client(monkeypatch)
    monkeypatch.setattr(site_assets.settings, "data_dir", tmp_path)
    image = b"\x89PNG\r\n\x1a\ncloudsite-share-page"

    async with client:
        uploaded = await client.post(
            "/api/admin/site/share-image",
            files={"file": ("share.png", image, "image/png")},
        )
        assert uploaded.status_code == 200
        assert uploaded.json()["share_image_url"] == "/api/public/share-page/image"

        settings = await client.get("/api/public/share-page")
        assert settings.json()["share_image_url"] == "/api/public/share-page/image"

        public_image = await client.get("/api/public/share-page/image")
        assert public_image.status_code == 200
        assert public_image.headers["content-type"] == "image/png"
        assert public_image.content == image

        removed = await client.delete("/api/admin/site/share-image")
        assert removed.status_code == 200
        assert (await client.get("/api/public/share-page/image")).status_code == 404

    await engine.dispose()


async def test_preview_ticket_is_resource_bound_time_limited_and_does_not_open_other_routes(monkeypatch):
    client, _, engine = await boundary_client(monkeypatch)
    class EmptyIndexSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, *_args):
            return None

    monkeypatch.setattr(main, "IndexSession", EmptyIndexSession)
    now = 1_800_000_000
    ticket = create_preview_ticket("not-a-resource", now=now)
    monkeypatch.setattr("cloudsite.preview.time.time", lambda: now)
    async with client:
        accepted = await client.get(f"/p/not-a-resource?ticket={ticket}", follow_redirects=False)
        assert accepted.status_code == 302
        assert accepted.headers["location"].startswith("/resource/not-a-resource?preview_error=")

        wrong_resource = await client.get(f"/p/other-resource?ticket={ticket}", follow_redirects=False)
        assert wrong_resource.status_code == 401
        assert wrong_resource.json()["detail"]["code"] == "AUTH_REQUIRED"

        monkeypatch.setattr("cloudsite.preview.time.time", lambda: now + PREVIEW_TICKET_TTL_SECONDS + 1)
        expired = await client.get(f"/p/not-a-resource?ticket={ticket}", follow_redirects=False)
        assert expired.status_code == 401
        assert expired.json()["detail"]["code"] == "AUTH_REQUIRED"

        protected = await client.get(f"/api/home?ticket={ticket}")
        assert protected.status_code == 401
        assert protected.json()["detail"]["code"] == "AUTH_REQUIRED"
    await engine.dispose()


async def test_valid_forged_and_expired_sessions(monkeypatch):
    client, factory, engine = await boundary_client(monkeypatch)
    async with factory() as session:
        now = utcnow()
        user = User(
            username="boundary_user",
            username_normalized="boundary_user",
            password_hash=auth.password_hash.hash("boundary-pass-123"),
            status="active",
            created_at=now,
            updated_at=now,
        )
        session.add(user)
        await session.flush()
        row, token = await create_user_session(session, user.id, now)
        await session.commit()

    async with client:
        forged = await client.get("/api/auth/me", cookies={USER_SESSION_COOKIE: "forged-token"})
        assert forged.status_code == 401
        assert forged.json()["detail"]["code"] == "SESSION_INVALID"
        valid = await client.get("/api/auth/me", cookies={USER_SESSION_COOKIE: token})
        assert valid.status_code == 200
        assert valid.json()["user"]["username"] == "boundary_user"
        async with factory() as session:
            stored = await session.get(type(row), row.id)
            stored.expires_at = utcnow() - timedelta(seconds=1)
            await session.commit()
        expired = await client.get("/api/auth/me", cookies={USER_SESSION_COOKIE: token})
        assert expired.status_code == 401
        assert expired.json()["detail"]["code"] == "SESSION_EXPIRED"
    await engine.dispose()


async def test_username_admin_and_user_cookie_do_not_grant_admin_access(monkeypatch):
    client, factory, engine = await boundary_client(monkeypatch)
    async with factory() as session:
        now = utcnow()
        user = User(
            username="admin",
            username_normalized="admin",
            password_hash=auth.password_hash.hash("admin-pass-123"),
            status="active",
            created_at=now,
            updated_at=now,
        )
        session.add_all(
            [
                user,
                AListConnection(
                    id=1,
                    base_url="https://alist.example",
                    username="alist-admin",
                    password_ciphertext="not-used",
                    enabled=True,
                ),
            ]
        )
        await session.flush()
        _, token = await create_user_session(session, user.id, now)
        await session.commit()

    async with client:
        response = await client.get(
            "/api/admin/system",
            cookies={USER_SESSION_COOKIE: token},
        )
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "ADMIN_REQUIRED"
    await engine.dispose()
