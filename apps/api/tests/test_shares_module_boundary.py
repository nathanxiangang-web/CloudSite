"""Focused regression tests for the Shares module boundary."""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.database import StateBase
from cloudsite.models import Share as LegacyShare
from cloudsite.modules.shares.contracts.public import (
    cancel_share,
    delete_share,
    get_share,
    reset_share_code,
    restore_share,
    share_payload,
    share_status,
)
from cloudsite.modules.shares.domain.code import verify_share_code
from cloudsite.modules.shares.infrastructure.models import Share as ModuleShare


async def _store():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)
    return engine, factory


async def test_legacy_share_model_reexports_module_owner():
    assert LegacyShare is ModuleShare


async def test_share_lifecycle_runs_behind_public_contract():
    engine, factory = await _store()
    async with factory() as state:
        state.add(
            ModuleShare(
                token="module-share",
                object_type="resource",
                object_id="resource-1",
                enabled=True,
                access_mode="code",
                code_hash="legacy-hash",
                code_version=1,
            )
        )
        await state.commit()

        view = await get_share(state, "module-share")
        assert view is not None
        assert share_payload(view)["token"] == "module-share"
        assert share_status(view, target_valid=True) == "active"

        view = await cancel_share(state, "module-share")
        assert share_status(view, target_valid=True) == "cancelled"

        view = await restore_share(state, "module-share")
        assert share_status(view, target_valid=True) == "active"

        view, code = await reset_share_code(
            state,
            "module-share",
            secret_key="test-secret",
        )
        assert view.code_version == 2
        assert verify_share_code(
            view.token,
            code.lower(),
            view.code_hash,
            secret_key="test-secret",
        )

        await delete_share(state, "module-share")
        await state.commit()
        assert await get_share(state, "module-share") is None

    await engine.dispose()
