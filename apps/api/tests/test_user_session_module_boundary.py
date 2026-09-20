"""Regression coverage for Users-owned session persistence."""

from __future__ import annotations

import ast
import inspect

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import cloudsite.sessions as session_facade
from cloudsite.database import StateBase
from cloudsite.models import (
    User,
    UserSession as LegacyUserSession,
    utcnow,
)
from cloudsite.modules.users.contracts.public import (
    AuthenticatedUserView,
    UserSessionView,
    create_user_session_state,
    validate_user_session_state,
)
from cloudsite.modules.users.infrastructure.models import (
    UserSession as ModuleUserSession,
)


async def test_user_session_model_is_users_owned():
    assert LegacyUserSession is ModuleUserSession


async def test_session_contract_returns_neutral_views():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)

    async with factory() as state:
        now = utcnow()
        user = User(
            username="session-boundary",
            username_normalized="session-boundary",
            password_hash="not-used",
            status="active",
            created_at=now,
            updated_at=now,
        )
        state.add(user)
        await state.flush()

        session_view, token = await create_user_session_state(
            state,
            user_id=user.id,
            now=now,
        )
        await state.commit()

        assert type(session_view) is UserSessionView
        assert not hasattr(session_view, "session_token_hash")

        resolved_session, resolved_user = (
            await validate_user_session_state(
                state,
                token=token,
                now=now,
            )
        )
        assert type(resolved_session) is UserSessionView
        assert type(resolved_user) is AuthenticatedUserView
        assert resolved_user.id == user.id
        assert resolved_user.username == "session-boundary"
        assert not hasattr(resolved_user, "password_hash")

    await engine.dispose()


def test_root_session_facade_has_no_session_sql_or_shared_models():
    tree = ast.parse(inspect.getsource(session_facade))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")

    assert "sqlalchemy" not in imports
    assert not any(name.endswith("models") for name in imports)
    source = inspect.getsource(session_facade)
    assert "select(" not in source
    assert "update(" not in source
    assert "delete(" not in source
