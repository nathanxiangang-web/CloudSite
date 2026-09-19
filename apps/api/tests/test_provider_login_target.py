"""Regression coverage for the Providers admin-login read contract."""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.modules.providers.contracts.public import (
    ProviderLoginTarget,
    connection_login_target,
)
from cloudsite.modules.providers.infrastructure.models import AListConnection
from cloudsite.platform.db import StateBase


async def test_connection_login_target_hides_provider_orm():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)

    async with factory() as session:
        assert await connection_login_target(session) is None
        session.add(
            AListConnection(
                id=1,
                base_url="https://alist.example",
                username="stored-user",
                password_ciphertext="stored-secret",
                enabled=True,
            )
        )
        await session.commit()

    async with factory() as session:
        target = await connection_login_target(session)
        assert isinstance(target, ProviderLoginTarget)
        assert target.base_url == "https://alist.example"
        assert not hasattr(target, "username")
        assert not hasattr(target, "password_ciphertext")

    await engine.dispose()
