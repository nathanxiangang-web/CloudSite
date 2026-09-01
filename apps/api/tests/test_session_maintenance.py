from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cloudsite import sessions
from cloudsite.database import StateBase
from cloudsite.models import User, UserSession


NOW = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)


@asynccontextmanager
async def session_store(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)
    monkeypatch.setattr(sessions, "StateSession", factory)
    try:
        yield engine, factory
    finally:
        await engine.dispose()


async def add_user_session(
    factory,
    token_hash: str,
    *,
    expires_at: datetime,
    revoked_at: datetime | None = None,
    last_seen_at: datetime = NOW,
) -> int:
    async with factory() as session:
        user = await session.scalar(select(User).limit(1))
        if user is None:
            user = User(
                username="session_user",
                username_normalized="session_user",
                password_hash="not-used",
                status="active",
                created_at=NOW,
                updated_at=NOW,
            )
            session.add(user)
            await session.flush()
        row = UserSession(
            session_token_hash=token_hash,
            user_id=user.id,
            created_at=NOW,
            expires_at=expires_at,
            last_seen_at=last_seen_at,
            revoked_at=revoked_at,
        )
        session.add(row)
        await session.commit()
        return row.id


async def session_count(factory) -> int:
    async with factory() as session:
        return int(await session.scalar(select(func.count()).select_from(UserSession)) or 0)


async def test_active_session_not_cleaned(monkeypatch):
    async with session_store(monkeypatch) as (_, factory):
        await add_user_session(factory, "a" * 64, expires_at=NOW + timedelta(days=1))
        assert await sessions.cleanup_expired_user_sessions(NOW) == 0
        assert await session_count(factory) == 1


async def test_expired_session_cleanup(monkeypatch):
    async with session_store(monkeypatch) as (_, factory):
        await add_user_session(factory, "b" * 64, expires_at=NOW - timedelta(days=8))
        assert await sessions.cleanup_expired_user_sessions(NOW) == 1
        assert await session_count(factory) == 0


async def test_old_revoked_session_cleanup(monkeypatch):
    async with session_store(monkeypatch) as (_, factory):
        await add_user_session(
            factory,
            "c" * 64,
            expires_at=NOW + timedelta(days=20),
            revoked_at=NOW - timedelta(days=8),
        )
        assert await sessions.cleanup_expired_user_sessions(NOW) == 1
        assert await session_count(factory) == 0


async def test_recent_revoked_session_retained(monkeypatch):
    async with session_store(monkeypatch) as (_, factory):
        await add_user_session(
            factory,
            "d" * 64,
            expires_at=NOW + timedelta(days=20),
            revoked_at=NOW - timedelta(days=1),
        )
        assert await sessions.cleanup_expired_user_sessions(NOW) == 0
        assert await session_count(factory) == 1


async def test_last_seen_touch_is_throttled(monkeypatch):
    async with session_store(monkeypatch) as (_, factory):
        token = "touch-token"
        row_id = await add_user_session(
            factory,
            sessions.hash_session_token(token),
            expires_at=NOW + timedelta(days=1),
        )
        async with factory() as session:
            for _ in range(100):
                await sessions.validate_user_session(session, token, NOW + timedelta(minutes=1))
            await session.commit()
        async with factory() as session:
            row = await session.get(UserSession, row_id)
            assert sessions.as_utc(row.last_seen_at) == NOW

        async with factory() as session:
            await sessions.validate_user_session(session, token, NOW + timedelta(minutes=6))
            await session.commit()
        async with factory() as session:
            row = await session.get(UserSession, row_id)
            assert sessions.as_utc(row.last_seen_at) == NOW + timedelta(minutes=6)


async def test_session_token_lookup_uses_unique_index(monkeypatch):
    async with session_store(monkeypatch) as (engine, _):
        async with engine.connect() as connection:
            indexes = list((await connection.execute(text("PRAGMA index_list('user_sessions')"))).all())
            assert any(bool(row[2]) and "session_token_hash" in row[1] for row in indexes)
            plan = list(
                (
                    await connection.execute(
                        text(
                            "EXPLAIN QUERY PLAN SELECT id FROM user_sessions "
                            "WHERE session_token_hash = :token"
                        ),
                        {"token": "a" * 64},
                    )
                ).all()
            )
            assert any("INDEX" in str(row[3]).upper() for row in plan)
