"""Admin overview module-composition regression."""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import main, models  # noqa: F401 - register shared metadata
from cloudsite.modules.delivery.infrastructure.models import DownloadEvent
from cloudsite.modules.indexing.infrastructure.legacy_models import SyncRun
from cloudsite.modules.providers.infrastructure.models import AListConnection
from cloudsite.modules.resources.infrastructure.models import Folder, Resource
from cloudsite.platform.db import IndexBase, StateBase
from cloudsite.platform.observability import write_operation_log
from cloudsite.routers.admin import overview as overview_router


async def test_admin_overview_composes_module_owned_queries(monkeypatch):
    state_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    index_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    state_factory = async_sessionmaker(
        state_engine,
        expire_on_commit=False,
    )
    index_factory = async_sessionmaker(
        index_engine,
        expire_on_commit=False,
    )

    async with state_engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    async with index_engine.begin() as conn:
        await conn.run_sync(IndexBase.metadata.create_all)

    async with state_factory() as state:
        state.add(
            AListConnection(
                id=1,
                base_url="https://alist.example.com",
                username="admin",
                password_ciphertext="ciphertext",
                enabled=True,
                last_test_status="success",
            )
        )
        state.add_all(
            [
                DownloadEvent(
                    resource_id="r1",
                    result="failed",
                    error_code="DL-001",
                ),
                DownloadEvent(
                    resource_id="r1",
                    result="success",
                    error_code=None,
                ),
            ]
        )
        await write_operation_log(
            state,
            module="test",
            action="overview",
            message="overview log",
        )
        await state.commit()

    async with index_factory() as index:
        index.add(
            Folder(
                id="f1",
                name="Apps",
                path="/apps",
                parent_id=None,
                content_type="software",
                root_mapping_id=1,
                depth=0,
                status="active",
            )
        )
        index.add_all(
            [
                Resource(
                    id="r1",
                    name="tool.zip",
                    path="/apps/tool.zip",
                    parent_id="f1",
                    content_type="software",
                    root_mapping_id=1,
                    extension="zip",
                    mime_type="application/zip",
                    size=10,
                    status="active",
                ),
                Resource(
                    id="r2",
                    name="guide.pdf",
                    path="/apps/guide.pdf",
                    parent_id="f1",
                    content_type="document",
                    root_mapping_id=1,
                    extension="pdf",
                    mime_type="application/pdf",
                    size=20,
                    status="active",
                ),
                Resource(
                    id="r3",
                    name="gone.zip",
                    path="/apps/gone.zip",
                    parent_id="f1",
                    content_type="software",
                    root_mapping_id=1,
                    extension="zip",
                    mime_type="application/zip",
                    size=30,
                    status="missing",
                ),
            ]
        )
        index.add(
            SyncRun(
                sync_type="manual",
                status="success",
                folders_scanned=1,
                resources_scanned=2,
                added_count=2,
                updated_count=0,
                removed_count=0,
                duration_ms=800,
                roots_total=1,
                roots_completed=1,
                roots_failed=0,
            )
        )
        await index.commit()

    monkeypatch.setattr(main, "StateSession", state_factory)
    monkeypatch.setattr(main, "IndexSession", index_factory)

    async def _circuit():
        return {
            "open": False,
            "until": None,
            "reason": "",
        }

    monkeypatch.setattr(
        overview_router,
        "sync_circuit_status",
        _circuit,
    )

    payload = await overview_router.admin_overview()

    assert payload["resources"] == 2
    assert payload["folders"] == 1
    assert payload["download_failures"] == 1
    assert payload["alist_connected"] is True
    assert payload["type_counts"]["software"] == 1
    assert payload["type_counts"]["document"] == 1
    assert payload["latest_sync"]["resources_scanned"] == 2
    assert payload["latest_sync"]["added"] == 2
    assert payload["sync_circuit"]["open"] is False
    assert payload["logs"][0]["message"] == "overview log"

    await state_engine.dispose()
    await index_engine.dispose()
