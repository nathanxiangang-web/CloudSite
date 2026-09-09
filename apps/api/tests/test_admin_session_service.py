from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite.database import StateBase
from cloudsite.services.admin_sessions import (
    AdminSessionExpired,
    AdminSessionInvalid,
    AdminSessionRevoked,
    hash_admin_session_token,
    issue_admin_session,
    revoke_admin_session,
    validate_admin_session,
)


async def _session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)()


async def test_issue_persists_only_hash_and_validates(tmp_path):
    engine, state = await _session(tmp_path)
    issued = await issue_admin_session(
        state,
        principal="root",
        authority="alist:role:admin",
        created_ip="192.0.2.4",
        user_agent="test-agent",
    )
    await state.commit()
    assert issued.token not in issued.session.session_token_hash
    assert issued.session.session_token_hash == hash_admin_session_token(issued.token)
    assert issued.session.created_ip_hash != "192.0.2.4"
    validated = await validate_admin_session(state, issued.token)
    assert validated.principal == "root"
    await state.close()
    await engine.dispose()


async def test_logout_revokes_and_replay_fails(tmp_path):
    engine, state = await _session(tmp_path)
    issued = await issue_admin_session(state, principal="admin", authority="role:admin")
    assert await revoke_admin_session(state, issued.token, reason="logout") is True
    with pytest.raises(AdminSessionRevoked):
        await validate_admin_session(state, issued.token)
    assert await revoke_admin_session(state, issued.token, reason="again") is True
    await state.close()
    await engine.dispose()


async def test_expiry_and_unknown_token_fail_closed(tmp_path):
    engine, state = await _session(tmp_path)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    issued = await issue_admin_session(
        state,
        principal="admin",
        authority="role:admin",
        ttl_seconds=60,
        now=now,
    )
    with pytest.raises(AdminSessionExpired):
        await validate_admin_session(state, issued.token, now=now + timedelta(seconds=61))
    with pytest.raises(AdminSessionInvalid):
        await validate_admin_session(state, "not-a-real-token")
    await state.close()
    await engine.dispose()


async def test_epoch_change_invalidates_existing_session(tmp_path):
    from cloudsite.models import SystemSetting

    engine, state = await _session(tmp_path)
    state.add(SystemSetting(key="admin_session_epoch", value="1", value_type="integer"))
    await state.flush()
    issued = await issue_admin_session(state, principal="admin", authority="role:admin")
    setting = await state.get(SystemSetting, "admin_session_epoch")
    setting.value = "2"
    await state.flush()
    with pytest.raises(AdminSessionRevoked):
        await validate_admin_session(state, issued.token)
    await state.close()
    await engine.dispose()
