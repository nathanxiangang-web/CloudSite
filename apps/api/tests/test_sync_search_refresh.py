"""Sync composition keeps public search aligned with indexed inventory."""

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass

from cloudsite.tasks import sync as sync_tasks


class _Context(AbstractAsyncContextManager):
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc, tb):
        return False


@dataclass
class _RebuildResult:
    indexed: int


async def test_v2_sync_rebuilds_search_after_success(monkeypatch):
    calls: list[tuple[object, object]] = []
    state = object()
    index = object()

    async def fake_run(*, store_factory):
        assert store_factory is sync_tasks._production_indexing_store
        return {"status": "success", "engine": "v2"}

    async def fake_rebuild(got_state, got_index):
        calls.append((got_state, got_index))
        return _RebuildResult(indexed=7)

    monkeypatch.setattr(sync_tasks, "_run_indexing_v2_production", fake_run)
    monkeypatch.setattr(sync_tasks, "state_session", lambda: _Context(state))
    monkeypatch.setattr(sync_tasks, "index_session", lambda: _Context(index))
    monkeypatch.setattr(sync_tasks, "rebuild_public_search_index", fake_rebuild)

    result = await sync_tasks.run_indexing_v2_production()

    assert calls == [(state, index)]
    assert result["search_indexed"] == 7


async def test_v2_sync_rebuilds_search_after_partial_write(monkeypatch):
    calls = 0

    async def fake_run(*, store_factory):
        return {"status": "partial", "engine": "v2", "errors": ["root:2 failed"]}

    async def fake_rebuild(state, index):
        nonlocal calls
        calls += 1
        return _RebuildResult(indexed=3)

    monkeypatch.setattr(sync_tasks, "_run_indexing_v2_production", fake_run)
    monkeypatch.setattr(sync_tasks, "state_session", lambda: _Context(object()))
    monkeypatch.setattr(sync_tasks, "index_session", lambda: _Context(object()))
    monkeypatch.setattr(sync_tasks, "rebuild_public_search_index", fake_rebuild)

    result = await sync_tasks.run_indexing_v2_production()

    assert calls == 1
    assert result["status"] == "partial"
    assert result["search_indexed"] == 3


async def test_v2_sync_does_not_rebuild_search_when_skipped(monkeypatch):
    async def fake_run(*, store_factory):
        return {"status": "skipped", "engine": "v2"}

    async def fail_rebuild(state, index):
        raise AssertionError("search rebuild must not run for skipped sync")

    monkeypatch.setattr(sync_tasks, "_run_indexing_v2_production", fake_run)
    monkeypatch.setattr(sync_tasks, "rebuild_public_search_index", fail_rebuild)

    result = await sync_tasks.run_indexing_v2_production()

    assert result == {"status": "skipped", "engine": "v2"}
