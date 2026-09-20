"""Providers scan-source composition regressions."""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.modules.providers.application import scan_source
from cloudsite.modules.providers.contracts.public import (
    ProviderScanPort,
    enabled_provider_scan_sources,
)
from cloudsite.modules.providers.infrastructure.models import (
    AListConnection,
    ContentRootMapping,
)
from cloudsite.platform.db import StateBase


class FakeAListClient:
    created: list[tuple[str, str, str]] = []

    def __init__(self, base_url: str, username: str, password: str) -> None:
        self.created.append((base_url, username, password))

    async def list_path(
        self,
        path: str,
        refresh: bool = False,
        strict: bool = False,
    ):
        return []

    async def get_file_info(self, path: str):
        return {"name": path.rsplit("/", 1)[-1]}


async def _state_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)
    return engine, factory


async def test_scan_sources_hide_provider_persistence_and_credentials(monkeypatch):
    engine, factory = await _state_factory()
    FakeAListClient.created.clear()
    monkeypatch.setattr(scan_source, "AListClient", FakeAListClient)
    monkeypatch.setattr(scan_source, "decrypt_secret", lambda value: "secret")

    async with factory() as state:
        state.add(
            AListConnection(
                id=7,
                name="scan",
                base_url="https://alist.example.test",
                username="reader",
                password_ciphertext="cipher",
                enabled=True,
                provider_type="generic_alist",
            )
        )
        state.add_all(
            [
                ContentRootMapping(
                    id=11,
                    connection_id=7,
                    content_type="software",
                    display_name="Apps",
                    alist_path="/apps",
                    enabled=True,
                    sort_order=2,
                ),
                ContentRootMapping(
                    id=12,
                    connection_id=7,
                    content_type="video",
                    display_name="Hidden",
                    alist_path="/hidden",
                    enabled=False,
                    sort_order=1,
                ),
            ]
        )
        await state.commit()

        sources = await enabled_provider_scan_sources(state)

    assert len(sources) == 1
    source = sources[0]
    assert isinstance(source.provider, ProviderScanPort)
    assert not hasattr(source, "connection")
    assert not hasattr(source, "password")
    assert [
        (
            root.root_mapping_id,
            root.content_type,
            root.display_name,
            root.storage_path,
        )
        for root in source.roots
    ] == [(11, "software", "Apps", "/apps")]
    assert FakeAListClient.created == [
        ("https://alist.example.test", "reader", "secret")
    ]

    await engine.dispose()


async def test_scan_sources_preserve_no_enabled_connection_failure(monkeypatch):
    engine, factory = await _state_factory()
    monkeypatch.setattr(scan_source, "decrypt_secret", lambda value: "secret")

    async with factory() as state:
        with pytest.raises(RuntimeError, match="没有可用"):
            await enabled_provider_scan_sources(state)

    await engine.dispose()
