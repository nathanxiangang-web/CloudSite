"""R0 PR 03: reconcile rollback regression tests.

When run_indexing_v2 raises an exception or returns "partial", the per-root
session must NOT be committed — partial writes must be rolled back by the
session context manager. A failed root must not prevent other roots from
being processed and committed normally.
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cloudsite.modules.indexing.infrastructure.legacy_bridge import (
    run_indexing_v2_production,
)


class _FakeSession:
    """Tracks commit calls and supports async context manager."""

    def __init__(self) -> None:
        self.commit_calls = 0
        self.rolled_back = False

    async def commit(self) -> None:
        self.commit_calls += 1

    async def rollback(self) -> None:
        self.rolled_back = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeStore:
    """Minimal IndexingStore stub."""

    async def list_indexed(self, **kwargs):
        return []

    async def upsert(self, entries):
        return 0

    async def remove(self, ids):
        return 0

    async def touch(self, ids):
        return 0


def _make_source(root_count: int = 1):
    """Create a fake provider scan source with the given number of roots."""
    roots = []
    for i in range(root_count):
        root = MagicMock()
        root.storage_path = f"/test/{i}"
        root.content_type = "test"
        root.root_mapping_id = f"rm-{i}"
        roots.append(root)

    source = MagicMock()
    source.roots = roots
    source.provider = MagicMock()
    return [source]


@pytest.fixture
def patched_production(monkeypatch):
    """Patch DB and logging dependencies of run_indexing_v2_production."""
    sessions: list[_FakeSession] = []

    def fake_index_session():
        session = _FakeSession()
        sessions.append(session)
        return session

    def fake_state_session():
        return _FakeSession()

    async def fake_log(*args, **kwargs):
        pass

    async def fake_update_status(*args, **kwargs):
        pass

    async def fake_sources(state):
        return _make_source(root_count=2)

    monkeypatch.setattr(
        "cloudsite.platform.db.index_session", fake_index_session
    )
    monkeypatch.setattr(
        "cloudsite.platform.db.state_session", fake_state_session
    )
    monkeypatch.setattr(
        "cloudsite.modules.indexing.infrastructure.legacy_bridge._log_operation",
        fake_log,
    )
    monkeypatch.setattr(
        "cloudsite.modules.indexing.infrastructure.legacy_bridge._update_v2_sync_status",
        fake_update_status,
    )
    monkeypatch.setattr(
        "cloudsite.modules.providers.contracts.public.enabled_provider_scan_sources",
        fake_sources,
    )

    return sessions


async def test_reconcile_exception_rolls_back(patched_production, monkeypatch):
    """When run_indexing_v2 raises, session.commit must not be called."""
    call_count = 0

    async def exploding_run_indexing_v2(**kwargs):
        nonlocal call_count
        call_count += 1
        raise RuntimeError("reconcile exploded")

    monkeypatch.setattr(
        "cloudsite.modules.indexing.infrastructure.legacy_bridge.run_indexing_v2",
        exploding_run_indexing_v2,
    )

    result = await run_indexing_v2_production(store_factory=lambda s: _FakeStore())

    assert result["status"] == "partial"
    assert len(result["errors"]) == 2
    assert "reconcile exploded" in result["errors"][0]
    for session in patched_production:
        assert session.commit_calls == 0, "session must not be committed on exception"


async def test_reconcile_success_commits(patched_production, monkeypatch):
    """When run_indexing_v2 succeeds, session.commit must be called."""
    async def happy_run_indexing_v2(**kwargs):
        return {
            "status": "success",
            "engine": "v2",
            "categories_scanned": 1,
            "pages_fetched": 5,
            "writes": {"added": 3, "changed": 0, "removed": 0, "unchanged": 1},
            "suppressed_removals": 0,
            "errors": [],
        }

    monkeypatch.setattr(
        "cloudsite.modules.indexing.infrastructure.legacy_bridge.run_indexing_v2",
        happy_run_indexing_v2,
    )

    result = await run_indexing_v2_production(store_factory=lambda s: _FakeStore())

    assert result["status"] == "success"
    assert result["categories_scanned"] == 2
    for session in patched_production:
        assert session.commit_calls == 1, "session must be committed on success"


async def test_partial_root_no_commit(patched_production, monkeypatch):
    """A partial root must not commit; other roots must still commit normally."""
    call_count = 0

    async def mixed_run_indexing_v2(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {
                "status": "partial",
                "engine": "v2",
                "categories_scanned": 0,
                "pages_fetched": 0,
                "writes": {"added": 0, "changed": 0, "removed": 0, "unchanged": 0},
                "suppressed_removals": 0,
                "errors": ["category-x: ValueError: bad data"],
            }
        return {
            "status": "success",
            "engine": "v2",
            "categories_scanned": 1,
            "pages_fetched": 3,
            "writes": {"added": 2, "changed": 0, "removed": 0, "unchanged": 1},
            "suppressed_removals": 0,
            "errors": [],
        }

    monkeypatch.setattr(
        "cloudsite.modules.indexing.infrastructure.legacy_bridge.run_indexing_v2",
        mixed_run_indexing_v2,
    )

    result = await run_indexing_v2_production(store_factory=lambda s: _FakeStore())

    assert result["status"] == "partial"
    assert len(result["errors"]) == 1
    assert "bad data" in result["errors"][0]
    assert len(patched_production) == 2
    assert patched_production[0].commit_calls == 0, "partial root must not commit"
    assert patched_production[1].commit_calls == 1, "success root must commit"