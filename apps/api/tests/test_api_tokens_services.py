"""X2 API Token + Webhook service tests.

Covers: token creation/verification/revocation/scopes,
webhook endpoint CRUD, event dispatch with dedup, delivery tracking.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from cloudsite.database import StateBase
from cloudsite.services import api_tokens, webhooks


@pytest.fixture
async def state_session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'state.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(StateBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    yield factory
    await engine.dispose()


def _now():
    return datetime.now(timezone.utc)


async def test_create_token(state_session):
    async with state_session() as state:
        raw, token = await api_tokens.create_token(state, label="test", scopes=["entry:read"])
        await state.commit()
        assert token.token_id.startswith("at_")
        assert token.status == "active"
        assert len(raw) > 0


async def test_verify_token(state_session):
    async with state_session() as state:
        raw, token = await api_tokens.create_token(state, scopes=["entry:read"])
        await state.commit()
        verified = await api_tokens.verify_token(state, raw)
        assert verified.token_id == token.token_id


async def test_verify_token_invalid(state_session):
    async with state_session() as state:
        with pytest.raises(api_tokens.TokenInvalid):
            await api_tokens.verify_token(state, "invalid-token")


async def test_verify_token_revoked(state_session):
    async with state_session() as state:
        raw, token = await api_tokens.create_token(state, scopes=["entry:read"])
        await state.commit()
        await api_tokens.revoke_token(state, token.token_id)
        await state.commit()
        with pytest.raises(api_tokens.TokenInvalid):
            await api_tokens.verify_token(state, raw)


async def test_verify_token_scope_check(state_session):
    async with state_session() as state:
        raw, _ = await api_tokens.create_token(state, scopes=["entry:read"])
        await state.commit()
        await api_tokens.verify_token(state, raw, required_scope="entry:read")
        with pytest.raises(api_tokens.ScopeDenied):
            await api_tokens.verify_token(state, raw, required_scope="entry:write")


async def test_verify_token_wildcard_scope(state_session):
    async with state_session() as state:
        raw, _ = await api_tokens.create_token(state, scopes=["*"])
        await state.commit()
        await api_tokens.verify_token(state, raw, required_scope="anything")


async def test_revoke_token_not_found(state_session):
    async with state_session() as state:
        with pytest.raises(api_tokens.TokenNotFound):
            await api_tokens.revoke_token(state, "at_nonexistent")


async def test_list_tokens(state_session):
    async with state_session() as state:
        await api_tokens.create_token(state, label="A")
        await api_tokens.create_token(state, label="B")
        await state.commit()
        tokens = await api_tokens.list_tokens(state)
        assert len(tokens) == 2


async def test_token_hash_not_raw(state_session):
    async with state_session() as state:
        raw, token = await api_tokens.create_token(state)
        await state.commit()
        assert token.token_hash != raw
        assert len(token.token_hash) == 64


async def test_verify_token_future_expiration_after_reload(state_session):
    """A token with a future UTC expires_at verifies after commit + reload.

    SQLite returns a naive datetime on reload; the service must normalize it
    so the comparison against utcnow() never raises TypeError.
    """
    expires_at = _now() + timedelta(hours=1)
    async with state_session() as state:
        raw, token = await api_tokens.create_token(
            state, scopes=["entry:read"], expires_at=expires_at
        )
        await state.commit()
        token_id = token.token_id
    async with state_session() as state:
        verified = await api_tokens.verify_token(state, raw)
        assert verified.token_id == token_id
        assert verified.status == "active"


async def test_verify_token_expired_after_reload(state_session):
    """A token whose expires_at is in the past is rejected after reload."""
    expires_at = _now() - timedelta(hours=1)
    async with state_session() as state:
        raw, token = await api_tokens.create_token(
            state, scopes=["entry:read"], expires_at=expires_at
        )
        await state.commit()
    async with state_session() as state:
        with pytest.raises(api_tokens.TokenInvalid) as exc_info:
            await api_tokens.verify_token(state, raw)
        assert "expired" in str(exc_info.value).lower()


async def test_verify_token_naive_expiration_treated_as_utc(state_session):
    """A timezone-naive expires_at input is treated as UTC and never raises TypeError."""
    naive_future = datetime.now() + timedelta(hours=1)
    assert naive_future.tzinfo is None
    async with state_session() as state:
        raw, token = await api_tokens.create_token(
            state, scopes=["entry:read"], expires_at=naive_future
        )
        await state.commit()
        assert token.expires_at is not None
        assert token.expires_at.tzinfo is not None
    async with state_session() as state:
        verified = await api_tokens.verify_token(state, raw)
        assert verified.status == "active"


async def test_verify_token_revoked_wins_over_expiration(state_session):
    """Immediate revocation still takes precedence over expiration checks."""
    expires_at = _now() - timedelta(hours=1)
    async with state_session() as state:
        raw, token = await api_tokens.create_token(
            state, scopes=["entry:read"], expires_at=expires_at
        )
        await state.commit()
        await api_tokens.revoke_token(state, token.token_id)
        await state.commit()
    async with state_session() as state:
        with pytest.raises(api_tokens.TokenInvalid) as exc_info:
            await api_tokens.verify_token(state, raw)
        assert "revoked" in str(exc_info.value).lower()


async def test_verify_token_expiration_preserves_scope_check(state_session):
    """Scope checks still apply to tokens carrying an expiration."""
    expires_at = _now() + timedelta(hours=1)
    async with state_session() as state:
        raw, _ = await api_tokens.create_token(
            state, scopes=["entry:read"], expires_at=expires_at
        )
        await state.commit()
    async with state_session() as state:
        await api_tokens.verify_token(state, raw, required_scope="entry:read")
        with pytest.raises(api_tokens.ScopeDenied):
            await api_tokens.verify_token(state, raw, required_scope="entry:write")


async def test_create_endpoint(state_session):
    async with state_session() as state:
        ep = await webhooks.create_endpoint(
            state,
            url="https://example.com/hook",
            event_types=["entry.created"],
        )
        await state.commit()
        assert ep.endpoint_id.startswith("wh_")
        assert ep.status == "active"
        assert ep.secret is not None


async def test_list_endpoints(state_session):
    async with state_session() as state:
        await webhooks.create_endpoint(state, url="https://a.com", event_types=[])
        await webhooks.create_endpoint(state, url="https://b.com", event_types=[])
        await state.commit()
        endpoints = await webhooks.list_endpoints(state)
        assert len(endpoints) == 2


async def test_update_endpoint(state_session):
    async with state_session() as state:
        ep = await webhooks.create_endpoint(state, url="https://a.com", event_types=[])
        await state.commit()
        updated = await webhooks.update_endpoint(state, ep.endpoint_id, status="disabled")
        await state.commit()
        assert updated.status == "disabled"


async def test_delete_endpoint(state_session):
    async with state_session() as state:
        ep = await webhooks.create_endpoint(state, url="https://a.com", event_types=[])
        await state.commit()
        await webhooks.delete_endpoint(state, ep.endpoint_id)
        await state.commit()
        endpoints = await webhooks.list_endpoints(state)
        assert len(endpoints) == 0


async def test_dispatch_event(state_session):
    async with state_session() as state:
        await webhooks.create_endpoint(
            state,
            url="https://example.com/hook",
            event_types=["entry.created"],
        )
        await state.commit()
        deliveries = await webhooks.dispatch_event(
            state,
            event_type="entry.created",
            event_data={"entry_id": "e1"},
        )
        await state.commit()
        assert len(deliveries) == 1
        assert deliveries[0].status == "pending"


async def test_dispatch_event_filtered(state_session):
    async with state_session() as state:
        await webhooks.create_endpoint(
            state,
            url="https://example.com/hook",
            event_types=["release.published"],
        )
        await state.commit()
        deliveries = await webhooks.dispatch_event(
            state,
            event_type="entry.created",
            event_data={},
        )
        await state.commit()
        assert len(deliveries) == 0


async def test_dispatch_event_dedup(state_session):
    async with state_session() as state:
        await webhooks.create_endpoint(
            state,
            url="https://example.com/hook",
            event_types=["entry.created"],
        )
        await state.commit()
        await webhooks.dispatch_event(state, "entry.created", {}, event_id="evt2")
        await webhooks.dispatch_event(state, "entry.created", {}, event_id="evt2")
        await state.commit()
        deliveries = await webhooks.list_deliveries(state)
        assert len(deliveries) == 1


async def test_list_deliveries(state_session):
    async with state_session() as state:
        ep = await webhooks.create_endpoint(
            state,
            url="https://example.com/hook",
            event_types=["entry.created"],
        )
        await state.commit()
        await webhooks.dispatch_event(state, "entry.created", {})
        await state.commit()
        deliveries = await webhooks.list_deliveries(state, endpoint_id=ep.endpoint_id)
        assert len(deliveries) == 1


async def test_mark_delivered(state_session):
    async with state_session() as state:
        await webhooks.create_endpoint(
            state,
            url="https://example.com/hook",
            event_types=["entry.created"],
        )
        await state.commit()
        deliveries = await webhooks.dispatch_event(state, "entry.created", {})
        await state.commit()
        d = await webhooks.mark_delivered(state, deliveries[0].delivery_id, 200, "ok")
        await state.commit()
        assert d.status == "delivered"
        assert d.response_code == 200


async def test_mark_failed(state_session):
    async with state_session() as state:
        await webhooks.create_endpoint(
            state,
            url="https://example.com/hook",
            event_types=["entry.created"],
        )
        await state.commit()
        deliveries = await webhooks.dispatch_event(state, "entry.created", {})
        await state.commit()
        d = await webhooks.mark_failed(state, deliveries[0].delivery_id, 500, "error")
        await state.commit()
        assert d.status == "failed"
        assert d.next_retry_at is not None


async def test_sign_payload():
    sig = webhooks.sign_payload("secret", '{"test": true}')
    assert len(sig) == 64


async def test_get_pending_deliveries(state_session):
    async with state_session() as state:
        await webhooks.create_endpoint(
            state,
            url="https://example.com/hook",
            event_types=["entry.created"],
        )
        await state.commit()
        await webhooks.dispatch_event(state, "entry.created", {})
        await state.commit()
        pending = await webhooks.get_pending_deliveries(state)
        assert len(pending) == 1