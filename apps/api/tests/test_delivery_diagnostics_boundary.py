"""Delivery admin diagnostics boundary regression."""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import models  # noqa: F401 - register shared metadata
from cloudsite.modules.delivery.contracts.public import (
    diagnose_download,
    list_download_diagnostics,
)
from cloudsite.modules.providers.contracts.public import (
    ProviderEntry,
    ProviderUnavailableError,
)
from cloudsite.modules.resources.contracts.public import DiagnosticResourceView
from cloudsite.platform.db import StateBase


class _Runtime:
    async def download_entry(self, *, root_mapping_id: int, path: str):
        assert root_mapping_id == 1
        assert path == "/apps/a.zip"
        return ProviderEntry(
            url="https://alist.example.com/d/apps/a.zip?sign=x",
            host="alist.example.com",
            base_path="/",
            has_sign=True,
        )

    async def preview_entry(self, *, root_mapping_id: int, path: str):
        return await self.download_entry(
            root_mapping_id=root_mapping_id,
            path=path,
        )


class _UnavailableRuntime:
    async def download_entry(self, *, root_mapping_id: int, path: str):
        raise ProviderUnavailableError("offline")

    async def preview_entry(self, *, root_mapping_id: int, path: str):
        raise ProviderUnavailableError("offline")


async def _store():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    return engine, factory


async def test_delivery_diagnostics_missing_inactive_success_and_history():
    engine, factory = await _store()

    active = DiagnosticResourceView(
        id="r_active",
        name="a.zip",
        path="/apps/a.zip",
        status="active",
        root_mapping_id=1,
        content_type="software",
    )
    inactive = DiagnosticResourceView(
        id="r_inactive",
        name="blocked.zip",
        path="/apps/blocked.zip",
        status="blocked",
        root_mapping_id=1,
        content_type="software",
    )

    async with factory() as state:
        missing = await diagnose_download(
            state,
            resource_id="r_missing",
            resource=None,
            provider_runtime=_Runtime(),
        )
        assert missing["status"] == "failed"
        assert missing["error_code"] == "DL-001"
        assert missing["failed_step"] == "resource_lookup"

    async with factory() as state:
        blocked = await diagnose_download(
            state,
            resource_id=inactive.id,
            resource=inactive,
            provider_runtime=_Runtime(),
        )
        assert blocked["status"] == "failed"
        assert blocked["error_code"] == "DL-007"
        assert blocked["failed_step"] == "resource_status"

    async with factory() as state:
        success = await diagnose_download(
            state,
            resource_id=active.id,
            resource=active,
            provider_runtime=_Runtime(),
        )
        assert success["status"] == "success"
        assert success["target_host"] == "alist.example.com"
        assert success["has_sign"] is True
        assert success["resource_name"] == "a.zip"
        assert success["steps"][-1]["name"] == "redirect_ready"

    async with factory() as state:
        history = await list_download_diagnostics(state, limit=10)
        assert [row["resource_id"] for row in history] == [
            "r_active",
            "r_inactive",
            "r_missing",
        ]

    await engine.dispose()


async def test_delivery_diagnostics_maps_provider_failure():
    engine, factory = await _store()
    resource = DiagnosticResourceView(
        id="r1",
        name="a.zip",
        path="/apps/a.zip",
        status="active",
        root_mapping_id=1,
        content_type="software",
    )

    async with factory() as state:
        result = await diagnose_download(
            state,
            resource_id=resource.id,
            resource=resource,
            provider_runtime=_UnavailableRuntime(),
        )
        assert result["status"] == "failed"
        assert result["error_code"] == "DL-002"
        assert result["failed_step"] == "alist_connection"
        assert result["has_sign"] is False

    await engine.dispose()
