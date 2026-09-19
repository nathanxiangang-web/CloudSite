"""Platform DB session factory lookup tests."""

from cloudsite import database
from cloudsite.platform.db import session as platform_session


async def test_state_session_resolves_current_database_factory(monkeypatch):
    marker = object()
    calls = []

    class Context:
        async def __aenter__(self):
            calls.append("enter")
            return marker

        async def __aexit__(self, *_args):
            calls.append("exit")

    monkeypatch.setattr(database, "StateSession", lambda: Context())

    async with platform_session.state_session() as session:
        assert session is marker

    assert calls == ["enter", "exit"]


async def test_get_state_session_resolves_current_database_factory(monkeypatch):
    marker = object()
    monkeypatch.setattr(database, "StateSession", lambda: marker)

    assert await platform_session.get_state_session() is marker


async def test_state_session_prefers_explicit_compatibility_hook(monkeypatch):
    dynamic_marker = object()
    override_marker = object()

    class DynamicContext:
        async def __aenter__(self):
            return dynamic_marker

        async def __aexit__(self, *_args):
            return None

    class OverrideContext:
        async def __aenter__(self):
            return override_marker

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setattr(database, "StateSession", lambda: DynamicContext())
    monkeypatch.setattr(platform_session, "StateSession", lambda: OverrideContext())

    async with platform_session.state_session() as session:
        assert session is override_marker
