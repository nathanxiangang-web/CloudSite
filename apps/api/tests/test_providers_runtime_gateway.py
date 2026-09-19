"""Providers runtime gateway tests."""

from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.modules.providers.domain.runtime import (
    ProviderAccessError,
    ProviderUnavailableError,
)
from cloudsite.modules.providers.infrastructure import runtime_gateway as runtime_mod
from cloudsite.modules.providers.infrastructure.models import (
    AListConnection,
    ContentRootMapping,
)
from cloudsite.modules.providers.infrastructure.runtime_gateway import (
    SqlAlchemyProviderRuntimeGateway,
)
from cloudsite.platform.db import StateBase


async def _factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    return engine, factory


async def _seed(factory, *, mapping_enabled=True, connection_enabled=True):
    async with factory() as session:
        session.add(
            AListConnection(
                id=7,
                name="provider-seven",
                base_url="https://alist.example",
                username="user-seven",
                password_ciphertext="encrypted-seven",
                enabled=connection_enabled,
            )
        )
        session.add(
            ContentRootMapping(
                id=11,
                connection_id=7,
                content_type="document",
                display_name="Docs",
                alist_path="/docs",
                enabled=mapping_enabled,
            )
        )
        await session.commit()


class FakeClient:
    instances = []

    def __init__(self, base_url, username, password):
        self.base_url = base_url
        self.username = username
        self.password = password
        self.paths = []
        type(self).instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get_download_entry(self, path):
        self.paths.append(("download", path))
        return SimpleNamespace(
            url="https://alist.example/d/docs/manual.pdf?sign=downloaded",
            host="alist.example",
            base_path="/docs",
            has_sign=True,
        )

    async def get_preview_entry(self, path):
        self.paths.append(("preview", path))
        return SimpleNamespace(
            url="https://alist.example/d/docs/manual.pdf?sign=signed",
            host="alist.example",
            base_path="/docs",
            has_sign=True,
        )


async def test_runtime_gateway_keeps_credentials_inside_providers(monkeypatch):
    engine, factory = await _factory()
    await _seed(factory)
    FakeClient.instances.clear()

    monkeypatch.setattr(runtime_mod, "decrypt_secret", lambda value: f"plain:{value}")
    monkeypatch.setattr(runtime_mod, "AListClient", FakeClient)

    async with factory() as session:
        gateway = SqlAlchemyProviderRuntimeGateway(session)

        download = await gateway.download_entry(
            root_mapping_id=11,
            path="/docs/manual.pdf",
        )
        entry = await gateway.preview_entry(
            root_mapping_id=11,
            path="/docs/manual.pdf",
        )

    assert download.url.startswith("https://alist.example/d/")
    assert download.host == "alist.example"
    assert download.base_path == "/docs"
    assert download.has_sign is True
    assert entry.url.startswith("https://alist.example/d/")
    assert entry.host == "alist.example"
    assert entry.base_path == "/docs"
    assert entry.has_sign is True
    assert not hasattr(entry, "password")
    assert not hasattr(entry, "password_ciphertext")

    assert len(FakeClient.instances) == 2
    for client in FakeClient.instances:
        assert client.base_url == "https://alist.example"
        assert client.username == "user-seven"
        assert client.password == "plain:encrypted-seven"

    await engine.dispose()


async def test_runtime_gateway_fails_closed_for_mapping_or_connection():
    engine, factory = await _factory()
    await _seed(factory, mapping_enabled=False)

    async with factory() as session:
        gateway = SqlAlchemyProviderRuntimeGateway(session)
        with pytest.raises(ProviderUnavailableError):
            await gateway.download_entry(root_mapping_id=11, path="/docs/a.txt")

    await engine.dispose()

    engine, factory = await _factory()
    await _seed(factory, connection_enabled=False)

    async with factory() as session:
        gateway = SqlAlchemyProviderRuntimeGateway(session)
        with pytest.raises(ProviderUnavailableError):
            await gateway.preview_entry(root_mapping_id=11, path="/docs/a.txt")

    await engine.dispose()


async def test_runtime_gateway_wraps_provider_failures(monkeypatch):
    engine, factory = await _factory()
    await _seed(factory)

    class BrokenClient(FakeClient):
        async def get_download_entry(self, path):
            raise RuntimeError("secret upstream detail")

    monkeypatch.setattr(runtime_mod, "decrypt_secret", lambda _value: "plain")
    monkeypatch.setattr(runtime_mod, "AListClient", BrokenClient)

    async with factory() as session:
        gateway = SqlAlchemyProviderRuntimeGateway(session)
        with pytest.raises(ProviderAccessError) as raised:
            await gateway.download_entry(
                root_mapping_id=11,
                path="/docs/manual.pdf",
            )

    assert raised.value.category == "unknown"
    assert raised.value.status_code == 502
    assert "secret upstream detail" not in str(raised.value)
    await engine.dispose()


async def test_runtime_gateway_preserves_normalized_alist_error_category(monkeypatch):
    engine, factory = await _factory()
    await _seed(factory)

    class UnreachableClient(FakeClient):
        async def get_preview_entry(self, path):
            from cloudsite.alist import AListError

            raise AListError(
                "private upstream network detail",
                "AL-002",
                status_code=502,
            )

    monkeypatch.setattr(runtime_mod, "decrypt_secret", lambda _value: "plain")
    monkeypatch.setattr(runtime_mod, "AListClient", UnreachableClient)

    async with factory() as session:
        gateway = SqlAlchemyProviderRuntimeGateway(session)
        with pytest.raises(ProviderAccessError) as raised:
            await gateway.preview_entry(
                root_mapping_id=11,
                path="/docs/manual.pdf",
            )

    assert raised.value.category == "unreachable"
    assert raised.value.status_code == 503
    assert "private upstream network detail" not in str(raised.value)
    await engine.dispose()
