"""Focused route tests for the administrator parser candidate API.

Covers:
- route registration and anonymous rejection
- validated bounds (invalid status/limit/offset rejected at the HTTP boundary)
- unchanged enqueue is idempotent; changed parser input creates a new candidate
- bounded batch execution with item and time bounds
- retry of one failed task
- restart recovery of interrupted running candidates
- proof that Catalog rows are not changed by any admin candidate operation
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import auth, main
from cloudsite.database import IndexBase, StateBase
from cloudsite.models import (
    CatalogAsset,
    CatalogEntry,
    CatalogRelease,
    ContentRootMapping,
    Resource,
    SiteSettings,
    SystemSetting,
    utcnow,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iter_routes(source):
    for route in getattr(source, "routes", []):
        original = getattr(route, "original_router", None)
        if original is not None and not hasattr(route, "path"):
            yield from _iter_routes(original)
        else:
            yield route


def _resource(
    resource_id: str = "r_test_1",
    name: str = "Tool-1.0.0-windows-x64.zip",
) -> Resource:
    return Resource(
        id=resource_id,
        name=name,
        path=f"/software/{name}",
        content_type="software",
        extension="zip",
        mime_type="application/zip",
        status="active",
        indexed_at=datetime.now(timezone.utc),
    )


async def _setup(monkeypatch, *, with_catalog: bool = False):
    """Create initialized state and index databases and patch main/auth."""
    state_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    index_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)
    state_factory = async_sessionmaker(state_engine, expire_on_commit=False)
    index_factory = async_sessionmaker(index_engine, expire_on_commit=False)

    async with state_factory() as state:
        state.add_all(
            [
                SiteSettings(id=1),
                SystemSetting(
                    key="setup_completed", value="true", value_type="string"
                ),
                ContentRootMapping(
                    id=1,
                    content_type="software",
                    display_name="Software",
                    alist_path="/software",
                    enabled=True,
                ),
            ]
        )
        if with_catalog:
            entry = CatalogEntry(
                entry_id="ce_" + "a" * 32,
                content_type="software",
                slug="shadow-app",
                title="Shadow App",
                status="published",
                revision=1,
            )
            release = CatalogRelease(
                release_id="cr_" + "b" * 32,
                entry_id=entry.entry_id,
                slug="1.0",
                title="1.0",
                status="published",
                channel="stable",
            )
            asset = CatalogAsset(
                asset_id="ca_" + "c" * 32,
                release_id=release.release_id,
                slug="windows-x64",
                display_name="app-1.0-windows-x64.zip",
                kind="file",
                architecture="x64",
                package_type="zip",
            )
            state.add_all([entry, release, asset])
        await state.commit()

    monkeypatch.setattr(main, "StateSession", state_factory)
    monkeypatch.setattr(main, "IndexSession", index_factory)
    monkeypatch.setattr(auth, "StateSession", state_factory)
    return state_engine, index_engine, state_factory, index_factory


def _admin_client(transport):
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    client.cookies.set(main.SESSION_COOKIE, main.create_session_token("admin"))
    return client


# ---------------------------------------------------------------------------
# 1. Route registration and anonymous rejection
# ---------------------------------------------------------------------------


def test_parser_candidate_routes_registered():
    found: dict[str, set[str]] = {}
    for route in _iter_routes(main.app):
        path = getattr(route, "path", "")
        if "parser-candidates" not in path:
            continue
        found.setdefault(path, set()).update(
            method
            for method in (getattr(route, "methods", None) or set())
            if method not in {"HEAD", "OPTIONS"}
        )
    assert found["/api/admin/parser-candidates"] == {"GET"}
    assert found["/api/admin/parser-candidates/enqueue"] == {"POST"}
    assert found["/api/admin/parser-candidates/batch"] == {"POST"}
    assert found["/api/admin/parser-candidates/recover"] == {"POST"}
    assert found["/api/admin/parser-candidates/{task_id}/retry"] == {"POST"}


async def test_anonymous_caller_rejected(monkeypatch):
    state_engine, index_engine, _, _ = await _setup(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        listing = await client.get("/api/admin/parser-candidates")
        assert listing.status_code == 403
        assert listing.json()["detail"]["code"] == "ADMIN_REQUIRED"

        enqueue = await client.post(
            "/api/admin/parser-candidates/enqueue",
            json={"resource_id": "r_test_1"},
        )
        assert enqueue.status_code == 403

        batch = await client.post(
            "/api/admin/parser-candidates/batch",
            json={"max_items": 1, "time_budget_seconds": 1.0},
        )
        assert batch.status_code == 403

        recover = await client.post("/api/admin/parser-candidates/recover")
        assert recover.status_code == 403
    await state_engine.dispose()
    await index_engine.dispose()


# ---------------------------------------------------------------------------
# 2. Validated bounds
# ---------------------------------------------------------------------------


async def test_list_rejects_invalid_status(monkeypatch):
    state_engine, index_engine, _, _ = await _setup(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    async with _admin_client(transport) as admin:
        response = await admin.get(
            "/api/admin/parser-candidates", params={"status": "unknown"}
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "PARSER_CANDIDATE_INVALID_STATUS"
    await state_engine.dispose()
    await index_engine.dispose()


async def test_list_rejects_invalid_limit_and_offset(monkeypatch):
    state_engine, index_engine, _, _ = await _setup(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    async with _admin_client(transport) as admin:
        too_small = await admin.get(
            "/api/admin/parser-candidates", params={"limit": 0}
        )
        assert too_small.status_code == 422

        too_large = await admin.get(
            "/api/admin/parser-candidates", params={"limit": 501}
        )
        assert too_large.status_code == 422

        neg_offset = await admin.get(
            "/api/admin/parser-candidates", params={"offset": -1}
        )
        assert neg_offset.status_code == 422
    await state_engine.dispose()
    await index_engine.dispose()


async def test_batch_rejects_invalid_bounds(monkeypatch):
    state_engine, index_engine, _, _ = await _setup(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    async with _admin_client(transport) as admin:
        zero_items = await admin.post(
            "/api/admin/parser-candidates/batch",
            json={"max_items": 0, "time_budget_seconds": 1.0},
        )
        assert zero_items.status_code == 422

        negative_budget = await admin.post(
            "/api/admin/parser-candidates/batch",
            json={"max_items": 1, "time_budget_seconds": -1.0},
        )
        assert negative_budget.status_code == 422

        too_many = await admin.post(
            "/api/admin/parser-candidates/batch",
            json={"max_items": 501, "time_budget_seconds": 1.0},
        )
        assert too_many.status_code == 422
    await state_engine.dispose()
    await index_engine.dispose()


async def test_list_accepts_valid_status_filters(monkeypatch):
    state_engine, index_engine, _, _ = await _setup(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    async with _admin_client(transport) as admin:
        for status in ("pending", "running", "completed", "failed", "cancelled"):
            response = await admin.get(
                "/api/admin/parser-candidates", params={"status": status}
            )
            assert response.status_code == 200, response.text
            assert response.json()["status"] == status
    await state_engine.dispose()
    await index_engine.dispose()


# ---------------------------------------------------------------------------
# 3. Unchanged enqueue is idempotent; changed input creates new candidate
# ---------------------------------------------------------------------------


async def test_enqueue_unchanged_is_idempotent(monkeypatch):
    state_engine, index_engine, _, index_factory = await _setup(monkeypatch)
    async with index_factory() as index:
        index.add(_resource())
        await index.commit()

    transport = httpx.ASGITransport(app=main.app)
    async with _admin_client(transport) as admin:
        first = await admin.post(
            "/api/admin/parser-candidates/enqueue",
            json={"resource_id": "r_test_1"},
        )
        assert first.status_code == 201, first.text
        assert first.json()["created"] is True
        task_id = first.json()["task"]["task_id"]

        second = await admin.post(
            "/api/admin/parser-candidates/enqueue",
            json={"resource_id": "r_test_1"},
        )
        assert second.status_code == 201, second.text
        assert second.json()["created"] is False
        assert second.json()["task"]["task_id"] == task_id
        assert second.json()["task"]["status"] == "pending"
    await state_engine.dispose()
    await index_engine.dispose()


async def test_enqueue_changed_input_creates_new_candidate(monkeypatch):
    state_engine, index_engine, _, index_factory = await _setup(monkeypatch)
    async with index_factory() as index:
        resource = _resource()
        index.add(resource)
        await index.commit()

    transport = httpx.ASGITransport(app=main.app)
    async with _admin_client(transport) as admin:
        first = await admin.post(
            "/api/admin/parser-candidates/enqueue",
            json={"resource_id": "r_test_1"},
        )
        assert first.status_code == 201
        first_fp = first.json()["task"]["input_fingerprint"]
        first_id = first.json()["task"]["task_id"]

        async with index_factory() as index:
            resource = await index.get(Resource, "r_test_1")
            resource.name = "Tool-2.0.0-linux-arm64.zip"
            resource.path = "/software/Tool-2.0.0-linux-arm64.zip"
            await index.commit()

        second = await admin.post(
            "/api/admin/parser-candidates/enqueue",
            json={"resource_id": "r_test_1"},
        )
        assert second.status_code == 201
        assert second.json()["created"] is True
        assert second.json()["task"]["task_id"] != first_id
        assert second.json()["task"]["input_fingerprint"] != first_fp
    await state_engine.dispose()
    await index_engine.dispose()


async def test_enqueue_rejects_missing_resource(monkeypatch):
    state_engine, index_engine, _, _ = await _setup(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    async with _admin_client(transport) as admin:
        response = await admin.post(
            "/api/admin/parser-candidates/enqueue",
            json={"resource_id": "r_missing"},
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "PARSER_CANDIDATE_ERROR"
    await state_engine.dispose()
    await index_engine.dispose()


# ---------------------------------------------------------------------------
# 4. Bounded batch execution
# ---------------------------------------------------------------------------


async def _seed_resources(index_factory, count: int):
    async with index_factory() as index:
        for i in range(count):
            index.add(
                _resource(
                    resource_id=f"r_batch_{i}",
                    name=f"Tool-{i}.0.0-windows-x64.zip",
                )
            )
        await index.commit()


async def test_batch_stops_at_max_items(monkeypatch):
    state_engine, index_engine, _, index_factory = await _setup(monkeypatch)
    await _seed_resources(index_factory, 3)
    transport = httpx.ASGITransport(app=main.app)
    async with _admin_client(transport) as admin:
        for i in range(3):
            await admin.post(
                "/api/admin/parser-candidates/enqueue",
                json={"resource_id": f"r_batch_{i}"},
            )

        result = await admin.post(
            "/api/admin/parser-candidates/batch",
            json={"max_items": 2, "time_budget_seconds": 30.0},
        )
        assert result.status_code == 200, result.text
        body = result.json()
        assert body["attempted"] == 2
        assert body["stopped_reason"] == "max_items"
        assert all(o["task"]["status"] == "completed" for o in body["outcomes"])

        remaining = await admin.get(
            "/api/admin/parser-candidates", params={"status": "pending"}
        )
        assert remaining.json()["total_returned"] == 1
    await state_engine.dispose()
    await index_engine.dispose()


async def test_batch_stops_at_time_budget(monkeypatch):
    state_engine, index_engine, _, index_factory = await _setup(monkeypatch)
    await _seed_resources(index_factory, 2)
    transport = httpx.ASGITransport(app=main.app)
    async with _admin_client(transport) as admin:
        for i in range(2):
            await admin.post(
                "/api/admin/parser-candidates/enqueue",
                json={"resource_id": f"r_batch_{i}"},
            )

        result = await admin.post(
            "/api/admin/parser-candidates/batch",
            json={"max_items": 100, "time_budget_seconds": 0.0},
        )
        assert result.status_code == 200, result.text
        body = result.json()
        assert body["attempted"] == 0
        assert body["stopped_reason"] == "time_budget"
        assert body["outcomes"] == []
    await state_engine.dispose()
    await index_engine.dispose()


async def test_batch_runs_all_when_budget_generous(monkeypatch):
    state_engine, index_engine, _, index_factory = await _setup(monkeypatch)
    await _seed_resources(index_factory, 2)
    transport = httpx.ASGITransport(app=main.app)
    async with _admin_client(transport) as admin:
        for i in range(2):
            await admin.post(
                "/api/admin/parser-candidates/enqueue",
                json={"resource_id": f"r_batch_{i}"},
            )

        result = await admin.post(
            "/api/admin/parser-candidates/batch",
            json={"max_items": 100, "time_budget_seconds": 30.0},
        )
        assert result.status_code == 200, result.text
        body = result.json()
        assert body["attempted"] == 2
        assert body["stopped_reason"] == "exhausted"
        assert all(o["task"]["status"] == "completed" for o in body["outcomes"])
    await state_engine.dispose()
    await index_engine.dispose()


# ---------------------------------------------------------------------------
# 5. Retry of one failed task
# ---------------------------------------------------------------------------


async def test_retry_failed_task(monkeypatch):
    state_engine, index_engine, state_factory, index_factory = await _setup(monkeypatch)
    async with index_factory() as index:
        index.add(_resource())
        await index.commit()

    transport = httpx.ASGITransport(app=main.app)
    async with _admin_client(transport) as admin:
        enqueued = await admin.post(
            "/api/admin/parser-candidates/enqueue",
            json={"resource_id": "r_test_1"},
        )
        task_id = enqueued.json()["task"]["task_id"]

        async with state_factory() as state:
            from cloudsite.services.parser_candidates import (
                claim_parser_candidate,
                fail_parser_candidate,
            )

            await claim_parser_candidate(state, task_id)
            await fail_parser_candidate(state, task_id, "synthetic failure")
            await state.commit()

        failed = await admin.get(
            "/api/admin/parser-candidates", params={"status": "failed"}
        )
        assert failed.json()["total_returned"] == 1

        retried = await admin.post(
            f"/api/admin/parser-candidates/{task_id}/retry",
            json={"max_retries": 3},
        )
        assert retried.status_code == 200, retried.text
        assert retried.json()["status"] == "pending"
        assert retried.json()["retry_count"] == 1

        pending = await admin.get(
            "/api/admin/parser-candidates", params={"status": "pending"}
        )
        assert pending.json()["total_returned"] == 1
    await state_engine.dispose()
    await index_engine.dispose()


async def test_retry_not_found(monkeypatch):
    state_engine, index_engine, _, _ = await _setup(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    async with _admin_client(transport) as admin:
        response = await admin.post(
            "/api/admin/parser-candidates/pt_nonexistent0000000000000000000000/retry",
            json={"max_retries": 3},
        )
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "PARSER_CANDIDATE_NOT_FOUND"
    await state_engine.dispose()
    await index_engine.dispose()


async def test_retry_limit_reached_returns_conflict(monkeypatch):
    state_engine, index_engine, state_factory, index_factory = await _setup(monkeypatch)
    async with index_factory() as index:
        index.add(_resource())
        await index.commit()

    transport = httpx.ASGITransport(app=main.app)
    async with _admin_client(transport) as admin:
        enqueued = await admin.post(
            "/api/admin/parser-candidates/enqueue",
            json={"resource_id": "r_test_1"},
        )
        task_id = enqueued.json()["task"]["task_id"]

        async with state_factory() as state:
            from cloudsite.services.parser_candidates import (
                claim_parser_candidate,
                fail_parser_candidate,
                retry_parser_candidate,
            )

            await claim_parser_candidate(state, task_id)
            await fail_parser_candidate(state, task_id, "fail once")
            await retry_parser_candidate(state, task_id, max_retries=3)
            await state.commit()

        conflict = await admin.post(
            f"/api/admin/parser-candidates/{task_id}/retry",
            json={"max_retries": 1},
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "PARSER_CANDIDATE_CONFLICT"
    await state_engine.dispose()
    await index_engine.dispose()


# ---------------------------------------------------------------------------
# 6. Restart recovery
# ---------------------------------------------------------------------------


async def test_recover_interrupted_candidates(monkeypatch):
    state_engine, index_engine, state_factory, index_factory = await _setup(monkeypatch)
    async with index_factory() as index:
        index.add_all(
            [
                _resource(resource_id="r_rc_1", name="A-1.0.0-windows-x64.zip"),
                _resource(resource_id="r_rc_2", name="B-2.0.0-linux-arm64.zip"),
            ]
        )
        await index.commit()

    transport = httpx.ASGITransport(app=main.app)
    async with _admin_client(transport) as admin:
        for rid in ("r_rc_1", "r_rc_2"):
            await admin.post(
                "/api/admin/parser-candidates/enqueue",
                json={"resource_id": rid},
            )

        task_ids: list[str] = []
        async with state_factory() as state:
            from cloudsite.services.parser_candidates import claim_parser_candidate

            pending = await admin.get(
                "/api/admin/parser-candidates", params={"status": "pending"}
            )
            task_ids = [item["task_id"] for item in pending.json()["items"]]
            for tid in task_ids:
                await claim_parser_candidate(state, tid)
            await state.commit()

        running = await admin.get(
            "/api/admin/parser-candidates", params={"status": "running"}
        )
        assert running.json()["total_returned"] == 2

        recovered = await admin.post("/api/admin/parser-candidates/recover")
        assert recovered.status_code == 200, recovered.text
        assert recovered.json()["recovered_count"] == 2
        assert all(
            r["status"] == "failed" for r in recovered.json()["recovered"]
        )

        running_after = await admin.get(
            "/api/admin/parser-candidates", params={"status": "running"}
        )
        assert running_after.json()["total_returned"] == 0

        failed_after = await admin.get(
            "/api/admin/parser-candidates", params={"status": "failed"}
        )
        assert failed_after.json()["total_returned"] == 2
    await state_engine.dispose()
    await index_engine.dispose()


async def test_recover_no_running_is_noop(monkeypatch):
    state_engine, index_engine, _, _ = await _setup(monkeypatch)
    transport = httpx.ASGITransport(app=main.app)
    async with _admin_client(transport) as admin:
        recovered = await admin.post("/api/admin/parser-candidates/recover")
        assert recovered.status_code == 200
        assert recovered.json()["recovered_count"] == 0
        assert recovered.json()["recovered"] == []
    await state_engine.dispose()
    await index_engine.dispose()


# ---------------------------------------------------------------------------
# 7. Catalog rows are not changed by any admin candidate operation
# ---------------------------------------------------------------------------


async def test_catalog_rows_unchanged_by_candidate_operations(monkeypatch):
    state_engine, index_engine, state_factory, index_factory = await _setup(
        monkeypatch, with_catalog=True
    )
    async with index_factory() as index:
        index.add(_resource())
        await index.commit()

    transport = httpx.ASGITransport(app=main.app)
    async with _admin_client(transport) as admin:
        await admin.post(
            "/api/admin/parser-candidates/enqueue",
            json={"resource_id": "r_test_1"},
        )
        await admin.post(
            "/api/admin/parser-candidates/batch",
            json={"max_items": 10, "time_budget_seconds": 30.0},
        )

        async with state_factory() as state:
            entry = await state.scalar(
                select(CatalogEntry).where(CatalogEntry.entry_id == "ce_" + "a" * 32)
            )
            assert entry is not None
            assert entry.title == "Shadow App"
            assert entry.slug == "shadow-app"
            assert entry.status == "published"
            assert entry.revision == 1

            release = await state.scalar(
                select(CatalogRelease).where(
                    CatalogRelease.release_id == "cr_" + "b" * 32
                )
            )
            assert release is not None
            assert release.slug == "1.0"
            assert release.status == "published"
            assert release.channel == "stable"

            asset = await state.scalar(
                select(CatalogAsset).where(
                    CatalogAsset.asset_id == "ca_" + "c" * 32
                )
            )
            assert asset is not None
            assert asset.display_name == "app-1.0-windows-x64.zip"
            assert asset.architecture == "x64"
            assert asset.package_type == "zip"

        completed = await admin.get(
            "/api/admin/parser-candidates", params={"status": "completed"}
        )
        assert completed.json()["total_returned"] == 1
    await state_engine.dispose()
    await index_engine.dispose()


async def test_catalog_rows_unchanged_by_retry_and_recover(monkeypatch):
    state_engine, index_engine, state_factory, index_factory = await _setup(
        monkeypatch, with_catalog=True
    )
    async with index_factory() as index:
        index.add(_resource())
        await index.commit()

    transport = httpx.ASGITransport(app=main.app)
    async with _admin_client(transport) as admin:
        enqueued = await admin.post(
            "/api/admin/parser-candidates/enqueue",
            json={"resource_id": "r_test_1"},
        )
        task_id = enqueued.json()["task"]["task_id"]

        async with state_factory() as state:
            from cloudsite.services.parser_candidates import (
                claim_parser_candidate,
                fail_parser_candidate,
            )

            await claim_parser_candidate(state, task_id)
            await fail_parser_candidate(state, task_id, "fail for catalog test")
            await state.commit()

        await admin.post(
            f"/api/admin/parser-candidates/{task_id}/retry",
            json={"max_retries": 3},
        )
        await admin.post("/api/admin/parser-candidates/recover")

        async with state_factory() as state:
            entry = await state.scalar(
                select(CatalogEntry).where(CatalogEntry.entry_id == "ce_" + "a" * 32)
            )
            assert entry is not None
            assert entry.title == "Shadow App"
            assert entry.revision == 1

            asset = await state.scalar(
                select(CatalogAsset).where(
                    CatalogAsset.asset_id == "ca_" + "c" * 32
                )
            )
            assert asset is not None
            assert asset.display_name == "app-1.0-windows-x64.zip"
    await state_engine.dispose()
    await index_engine.dispose()
