"""Regression tests for the admin sync module boundary."""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.database import StateBase
from cloudsite.models import ContentRootMapping, SystemSetting
from cloudsite.modules.indexing.contracts.public import (
    toggle_automatic_sync,
    validate_manual_sync_paths,
)


async def _store():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)
    return engine, factory


async def test_manual_path_validation_uses_provider_contract_roots():
    engine, factory = await _store()
    async with factory() as state:
        state.add_all(
            [
                ContentRootMapping(
                    id=1,
                    content_type="file",
                    display_name="enabled",
                    alist_path="/enabled",
                    enabled=True,
                ),
                ContentRootMapping(
                    id=2,
                    content_type="file",
                    display_name="disabled",
                    alist_path="/disabled",
                    enabled=False,
                ),
            ]
        )
        await state.commit()

        accepted, rejected = await validate_manual_sync_paths(
            state,
            [
                "/enabled/child",
                "\\enabled\\nested",
                "/disabled/file",
                "/enabled/../escape",
            ],
        )

        assert accepted == ["/enabled/child", "/enabled/nested"]
        assert rejected == [
            {
                "path": "/disabled/file",
                "reason": "路径不在任何已启用内容根下",
            },
            {
                "path": "/enabled/../escape",
                "reason": "路径包含非法的 .. 段",
            },
        ]

    await engine.dispose()


async def test_toggle_automatic_sync_persists_without_router_orm():
    engine, factory = await _store()
    async with factory() as state:
        assert await toggle_automatic_sync(state) is True
        row = await state.get(SystemSetting, "automatic_sync")
        assert row is not None
        assert row.value == "true"

        assert await toggle_automatic_sync(state) is False
        await state.refresh(row)
        assert row.value == "false"

    await engine.dispose()
