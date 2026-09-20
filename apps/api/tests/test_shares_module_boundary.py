"""Focused regression tests for the Shares module boundary."""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.database import StateBase
from cloudsite.models import Share as LegacyShare
from cloudsite.modules.shares.contracts.public import (
    cancel_share,
    challenge_required,
    cleanup_share_verify_attempts,
    clear_verify_attempts,
    delete_share,
    get_share,
    reset_share_code,
    restore_share,
    share_payload,
    share_status,
    verify_attempt_failed,
)
from cloudsite.modules.shares.domain.code import verify_share_code
from cloudsite.modules.shares.infrastructure.models import (
    Share as ModuleShare,
    ShareVerifyAttempt,
    utcnow,
)
from cloudsite.platform.db import session as db_session


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


async def test_verification_attempt_state_runs_behind_public_contract(monkeypatch):
    engine, factory = await _store()
    secret_key = "test-secret"
    address = "203.0.113.10"

    async with factory() as state:
        for _ in range(4):
            assert not await verify_attempt_failed(
                state,
                "module-share",
                address,
                secret_key=secret_key,
            )
        assert await verify_attempt_failed(
            state,
            "module-share",
            address,
            secret_key=secret_key,
        )
        await state.commit()

        assert await challenge_required(
            state,
            "module-share",
            address,
            secret_key=secret_key,
        )
        await clear_verify_attempts(
            state,
            "module-share",
            address,
            secret_key=secret_key,
        )
        await state.commit()
        assert not await challenge_required(
            state,
            "module-share",
            address,
            secret_key=secret_key,
        )

        now = utcnow()
        state.add_all(
            [
                ShareVerifyAttempt(
                    share_token="old",
                    ip_hash="old-hash",
                    fail_count=1,
                    window_started_at=now - timedelta(hours=2),
                    updated_at=now - timedelta(hours=2),
                ),
                ShareVerifyAttempt(
                    share_token="fresh",
                    ip_hash="fresh-hash",
                    fail_count=1,
                    window_started_at=now,
                    updated_at=now,
                ),
            ]
        )
        await state.commit()

    monkeypatch.setattr(db_session, "StateSession", factory)
    assert await cleanup_share_verify_attempts(now) == 1

    async with factory() as state:
        rows = list(
            (
                await state.scalars(
                    select(ShareVerifyAttempt).order_by(
                        ShareVerifyAttempt.share_token
                    )
                )
            ).all()
        )
        assert [row.share_token for row in rows] == ["fresh"]

    await engine.dispose()
