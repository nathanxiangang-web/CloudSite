"""D3 submission publish binding route tests.

Focused tests for the administrator publish action binding a submission to a
real, currently allowed file resource. Covers:
- valid result link stores published_resource_id and the file page can open it
- missing/out-of-scope rejection leaves status, binding, log, and notifications unchanged
- duplicate publish to the same bound resource is idempotent
- illegal transitions and different targets return 409
"""
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import auth, main
from cloudsite.database import IndexBase, StateBase
from cloudsite.models import (
    AListConnection,
    ContentRootMapping,
    Notification,
    OperationLog,
    Resource,
    SiteSettings,
    Submission,
    SystemSetting,
    User,
    utcnow,
)
from cloudsite.sessions import USER_SESSION_COOKIE, create_user_session


async def _publish_store(monkeypatch):
    """Create a test store: enabled root + disabled root with resources and a pending submission."""
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
        state.add(ContentRootMapping(id=1, content_type="software", display_name="enabled", alist_path="/enabled", enabled=True))
        state.add(ContentRootMapping(id=2, content_type="software", display_name="disabled", alist_path="/disabled", enabled=False))
        state.add(AListConnection(id=1, base_url="http://alist", username="admin", enabled=True))
        user = User(username="user", username_normalized="user", password_hash="x", status="active", created_at=utcnow(), updated_at=utcnow())
        state.add(user)
        await state.flush()
        _, user_token = await create_user_session(state, user.id, utcnow())
        state.add(Submission(
            id=1,
            user_id=user.id,
            resource_name="test resource",
            resource_type="software",
            description="",
            source_url="",
            download_url="",
            copyright_note="",
            note="",
            status="pending",
        ))
        await state.commit()

    async with index_factory() as index:
        index.add(Resource(id="r_enabled", name="enabled.zip", path="/enabled/enabled.zip", parent_id=None, content_type="software", root_mapping_id=1, extension="zip", mime_type="application/zip", size=100, thumbnail="", status="active"))
        index.add(Resource(id="r_enabled_pdf", name="enabled.pdf", path="/enabled/enabled.pdf", parent_id=None, content_type="software", root_mapping_id=1, extension="pdf", mime_type="application/pdf", size=100, thumbnail="", status="active"))
        index.add(Resource(id="r_disabled", name="disabled.zip", path="/disabled/disabled.zip", parent_id=None, content_type="software", root_mapping_id=2, extension="zip", mime_type="application/zip", size=200, thumbnail="", status="active"))
        index.add(Resource(id="r_inactive", name="inactive.zip", path="/enabled/inactive.zip", parent_id=None, content_type="software", root_mapping_id=1, extension="zip", mime_type="application/zip", size=100, thumbnail="", status="missing"))
        index.add(Resource(id="r_noroot", name="noroot.zip", path="/loose/noroot.zip", parent_id=None, content_type="software", root_mapping_id=None, extension="zip", mime_type="application/zip", size=100, thumbnail="", status="active"))
        await index.commit()

    return state_engine, index_engine, user_token


def _admin_cookies():
    return {main.SESSION_COOKIE: main.create_session_token("admin")}


async def _count_notifications(factory):
    async with factory() as state:
        rows = list((await state.scalars(select(Notification).where(Notification.source == "submission"))).all())
        return len(rows)


async def _count_operation_logs(factory):
    async with factory() as state:
        rows = list((await state.scalars(select(OperationLog).where(OperationLog.module == "submission"))).all())
        return len(rows)


async def _get_submission(factory):
    async with factory() as state:
        row = await state.get(Submission, 1)
        await state.commit()
        return {"status": row.status, "published_resource_id": row.published_resource_id}


async def test_publish_binds_real_resource_id_and_opens(monkeypatch):
    """A successful publish stores a real resource ID that the file page can open."""
    state_engine, index_engine, user_token = await _publish_store(monkeypatch)
    admin_cookies = _admin_cookies()
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        approve = await client.patch("/api/admin/submissions/1", json={"action": "approve"}, cookies=admin_cookies)
        assert approve.status_code == 200, approve.text
        assert approve.json()["status"] == "approved"

        publish = await client.patch("/api/admin/submissions/1", json={"action": "publish", "resource_id": "r_enabled"}, cookies=admin_cookies)
        assert publish.status_code == 200, publish.text
        body = publish.json()
        assert body["status"] == "published"
        assert body["published_resource_id"] == "r_enabled"

        resource_page = await client.get("/api/resources/r_enabled", cookies={USER_SESSION_COOKIE: user_token})
        assert resource_page.status_code == 200, resource_page.text
        assert resource_page.json()["id"] == "r_enabled"
    await state_engine.dispose()
    await index_engine.dispose()


async def test_publish_rejects_missing_resource_id(monkeypatch):
    """Publish without resource_id returns 400 and leaves state unchanged."""
    state_engine, index_engine, _ = await _publish_store(monkeypatch)
    state_factory = main.StateSession
    admin_cookies = _admin_cookies()
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        approve = await client.patch("/api/admin/submissions/1", json={"action": "approve"}, cookies=admin_cookies)
        assert approve.status_code == 200

        before = await _get_submission(state_factory)
        before_notifs = await _count_notifications(state_factory)
        before_logs = await _count_operation_logs(state_factory)

        publish = await client.patch("/api/admin/submissions/1", json={"action": "publish"}, cookies=admin_cookies)
        assert publish.status_code == 400, publish.text
        assert publish.json()["detail"]["code"] == "SUBMISSION_RESOURCE_REQUIRED"

        after = await _get_submission(state_factory)
        assert after == before
        assert await _count_notifications(state_factory) == before_notifs
        assert await _count_operation_logs(state_factory) == before_logs
    await state_engine.dispose()
    await index_engine.dispose()


async def test_publish_rejects_inactive_resource(monkeypatch):
    """Publish to an inactive resource returns 404 and leaves state unchanged."""
    state_engine, index_engine, _ = await _publish_store(monkeypatch)
    state_factory = main.StateSession
    admin_cookies = _admin_cookies()
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.patch("/api/admin/submissions/1", json={"action": "approve"}, cookies=admin_cookies)

        before = await _get_submission(state_factory)
        before_notifs = await _count_notifications(state_factory)
        before_logs = await _count_operation_logs(state_factory)

        publish = await client.patch("/api/admin/submissions/1", json={"action": "publish", "resource_id": "r_inactive"}, cookies=admin_cookies)
        assert publish.status_code == 404, publish.text
        assert publish.json()["detail"]["code"] == "SUBMISSION_RESOURCE_INVALID"

        after = await _get_submission(state_factory)
        assert after == before
        assert await _count_notifications(state_factory) == before_notifs
        assert await _count_operation_logs(state_factory) == before_logs
    await state_engine.dispose()
    await index_engine.dispose()


async def test_publish_rejects_disabled_root_resource(monkeypatch):
    """Publish to a resource under a disabled content root returns 404 and leaves state unchanged."""
    state_engine, index_engine, _ = await _publish_store(monkeypatch)
    state_factory = main.StateSession
    admin_cookies = _admin_cookies()
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.patch("/api/admin/submissions/1", json={"action": "approve"}, cookies=admin_cookies)

        before = await _get_submission(state_factory)
        before_notifs = await _count_notifications(state_factory)
        before_logs = await _count_operation_logs(state_factory)

        publish = await client.patch("/api/admin/submissions/1", json={"action": "publish", "resource_id": "r_disabled"}, cookies=admin_cookies)
        assert publish.status_code == 404, publish.text
        assert publish.json()["detail"]["code"] == "SUBMISSION_RESOURCE_OUT_OF_SCOPE"

        after = await _get_submission(state_factory)
        assert after == before
        assert await _count_notifications(state_factory) == before_notifs
        assert await _count_operation_logs(state_factory) == before_logs
    await state_engine.dispose()
    await index_engine.dispose()


async def test_publish_rejects_resource_without_root(monkeypatch):
    """Publish to a resource with no root mapping returns 404 and leaves state unchanged."""
    state_engine, index_engine, _ = await _publish_store(monkeypatch)
    state_factory = main.StateSession
    admin_cookies = _admin_cookies()
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.patch("/api/admin/submissions/1", json={"action": "approve"}, cookies=admin_cookies)

        before = await _get_submission(state_factory)
        before_notifs = await _count_notifications(state_factory)

        publish = await client.patch("/api/admin/submissions/1", json={"action": "publish", "resource_id": "r_noroot"}, cookies=admin_cookies)
        assert publish.status_code == 404, publish.text
        assert publish.json()["detail"]["code"] == "SUBMISSION_RESOURCE_OUT_OF_SCOPE"

        after = await _get_submission(state_factory)
        assert after == before
        assert await _count_notifications(state_factory) == before_notifs
    await state_engine.dispose()
    await index_engine.dispose()


async def test_publish_rejects_nonexistent_resource(monkeypatch):
    """Publish to a resource ID that does not exist in index.db returns 404."""
    state_engine, index_engine, _ = await _publish_store(monkeypatch)
    state_factory = main.StateSession
    admin_cookies = _admin_cookies()
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.patch("/api/admin/submissions/1", json={"action": "approve"}, cookies=admin_cookies)

        before = await _get_submission(state_factory)
        before_notifs = await _count_notifications(state_factory)

        publish = await client.patch("/api/admin/submissions/1", json={"action": "publish", "resource_id": "r_does_not_exist"}, cookies=admin_cookies)
        assert publish.status_code == 404, publish.text
        assert publish.json()["detail"]["code"] == "SUBMISSION_RESOURCE_INVALID"

        after = await _get_submission(state_factory)
        assert after == before
        assert await _count_notifications(state_factory) == before_notifs
    await state_engine.dispose()
    await index_engine.dispose()


async def test_duplicate_publish_is_idempotent(monkeypatch):
    """Repeating the same successful publish does not duplicate notification or mutation."""
    state_engine, index_engine, _ = await _publish_store(monkeypatch)
    state_factory = main.StateSession
    admin_cookies = _admin_cookies()
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.patch("/api/admin/submissions/1", json={"action": "approve"}, cookies=admin_cookies)
        first = await client.patch("/api/admin/submissions/1", json={"action": "publish", "resource_id": "r_enabled"}, cookies=admin_cookies)
        assert first.status_code == 200
        assert first.json()["published_resource_id"] == "r_enabled"

        notifs_after_first = await _count_notifications(state_factory)
        logs_after_first = await _count_operation_logs(state_factory)
        submission_after_first = await _get_submission(state_factory)

        second = await client.patch("/api/admin/submissions/1", json={"action": "publish", "resource_id": "r_enabled"}, cookies=admin_cookies)
        assert second.status_code == 200, second.text
        assert second.json()["published_resource_id"] == "r_enabled"
        assert second.json()["status"] == "published"

        assert await _count_notifications(state_factory) == notifs_after_first
        assert await _count_operation_logs(state_factory) == logs_after_first
        assert await _get_submission(state_factory) == submission_after_first
    await state_engine.dispose()
    await index_engine.dispose()


async def test_publish_different_target_returns_409(monkeypatch):
    """Publishing to a different resource after a successful publish returns 409."""
    state_engine, index_engine, _ = await _publish_store(monkeypatch)
    state_factory = main.StateSession
    admin_cookies = _admin_cookies()
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.patch("/api/admin/submissions/1", json={"action": "approve"}, cookies=admin_cookies)
        first = await client.patch("/api/admin/submissions/1", json={"action": "publish", "resource_id": "r_enabled"}, cookies=admin_cookies)
        assert first.status_code == 200

        notifs_before = await _count_notifications(state_factory)
        logs_before = await _count_operation_logs(state_factory)
        submission_before = await _get_submission(state_factory)

        second = await client.patch("/api/admin/submissions/1", json={"action": "publish", "resource_id": "r_enabled_pdf"}, cookies=admin_cookies)
        assert second.status_code == 409, second.text
        assert second.json()["detail"]["code"] == "SUBMISSION_ALREADY_PUBLISHED"

        assert await _count_notifications(state_factory) == notifs_before
        assert await _count_operation_logs(state_factory) == logs_before
        assert await _get_submission(state_factory) == submission_before
    await state_engine.dispose()
    await index_engine.dispose()


async def test_publish_without_approval_returns_409(monkeypatch):
    """Publishing a pending submission without prior approval returns 409."""
    state_engine, index_engine, _ = await _publish_store(monkeypatch)
    state_factory = main.StateSession
    admin_cookies = _admin_cookies()
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        before = await _get_submission(state_factory)
        before_notifs = await _count_notifications(state_factory)

        publish = await client.patch("/api/admin/submissions/1", json={"action": "publish", "resource_id": "r_enabled"}, cookies=admin_cookies)
        assert publish.status_code == 409, publish.text
        assert publish.json()["detail"]["code"] == "SUBMISSION_ILLEGAL_TRANSITION"

        assert await _get_submission(state_factory) == before
        assert await _count_notifications(state_factory) == before_notifs
    await state_engine.dispose()
    await index_engine.dispose()


async def test_approve_from_approved_returns_409(monkeypatch):
    """Approving an already-approved submission returns 409."""
    state_engine, index_engine, _ = await _publish_store(monkeypatch)
    admin_cookies = _admin_cookies()
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        first = await client.patch("/api/admin/submissions/1", json={"action": "approve"}, cookies=admin_cookies)
        assert first.status_code == 200
        second = await client.patch("/api/admin/submissions/1", json={"action": "approve"}, cookies=admin_cookies)
        assert second.status_code == 409, second.text
        assert second.json()["detail"]["code"] == "SUBMISSION_ILLEGAL_TRANSITION"
    await state_engine.dispose()
    await index_engine.dispose()


async def test_reject_from_approved_returns_409(monkeypatch):
    """Rejecting an already-approved submission returns 409."""
    state_engine, index_engine, _ = await _publish_store(monkeypatch)
    admin_cookies = _admin_cookies()
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        first = await client.patch("/api/admin/submissions/1", json={"action": "approve"}, cookies=admin_cookies)
        assert first.status_code == 200
        second = await client.patch("/api/admin/submissions/1", json={"action": "reject"}, cookies=admin_cookies)
        assert second.status_code == 409, second.text
        assert second.json()["detail"]["code"] == "SUBMISSION_ILLEGAL_TRANSITION"
    await state_engine.dispose()
    await index_engine.dispose()


async def test_reject_pending_submission_succeeds(monkeypatch):
    """Rejecting a pending submission succeeds and stores rejected status."""
    state_engine, index_engine, _ = await _publish_store(monkeypatch)
    admin_cookies = _admin_cookies()
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        reject = await client.patch("/api/admin/submissions/1", json={"action": "reject", "admin_note": "not suitable"}, cookies=admin_cookies)
        assert reject.status_code == 200, reject.text
        assert reject.json()["status"] == "rejected"
        assert reject.json()["published_resource_id"] is None
    await state_engine.dispose()
    await index_engine.dispose()


async def test_user_submission_end_to_end_publish_flow(monkeypatch):
    """User create -> admin approve -> publish -> user sees published binding."""
    state_engine, index_engine, user_token = await _publish_store(monkeypatch)
    admin_cookies = _admin_cookies()
    user_cookies = {USER_SESSION_COOKIE: user_token}
    transport = httpx.ASGITransport(app=main.app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        created = await client.post(
            "/api/submissions",
            json={
                "resource_name": "new app",
                "resource_type": "software",
                "description": "submitted by user",
                "source_url": "https://example.com/new-app",
                "download_url": "https://example.com/new-app.zip",
                "copyright_note": "",
                "note": "",
            },
            cookies=user_cookies,
        )
        assert created.status_code == 200, created.text
        submission_id = created.json()["id"]
        assert created.json()["resource_type"] == "software"
        assert created.json()["status"] == "pending"

        approve = await client.patch(
            f"/api/admin/submissions/{submission_id}",
            json={"action": "approve", "admin_note": "looks good"},
            cookies=admin_cookies,
        )
        assert approve.status_code == 200, approve.text
        assert approve.json()["status"] == "approved"

        publish = await client.patch(
            f"/api/admin/submissions/{submission_id}",
            json={
                "action": "publish",
                "resource_id": "r_enabled",
                "admin_note": "published",
            },
            cookies=admin_cookies,
        )
        assert publish.status_code == 200, publish.text
        assert publish.json()["status"] == "published"
        assert publish.json()["published_resource_id"] == "r_enabled"

        mine = await client.get(
            "/api/submissions/mine",
            cookies=user_cookies,
        )
        assert mine.status_code == 200, mine.text
        row = next(
            item
            for item in mine.json()["items"]
            if item["id"] == submission_id
        )
        assert row["resource_type"] == "software"
        assert row["status"] == "published"
        assert row["published_resource_id"] == "r_enabled"
        assert row["admin_note"] == "published"

        legacy_type = await client.post(
            "/api/submissions",
            json={
                "resource_name": "legacy type",
                "resource_type": "软件",
                "description": "invalid machine value",
            },
            cookies=user_cookies,
        )
        assert legacy_type.status_code == 422

    await state_engine.dispose()
    await index_engine.dispose()
