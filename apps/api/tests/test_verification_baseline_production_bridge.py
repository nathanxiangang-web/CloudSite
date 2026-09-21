"""Production bridge tests for durable verification baseline promotion."""

from __future__ import annotations

from contextlib import asynccontextmanager

import cloudsite.modules.indexing.infrastructure.alist_adapter as alist_adapter
import cloudsite.modules.indexing.infrastructure.legacy_bridge as legacy_bridge
import cloudsite.modules.indexing.infrastructure.verification_baseline as baseline_module
import cloudsite.modules.providers.contracts.public as provider_public
import cloudsite.platform.db as platform_db
from cloudsite.modules.providers.contracts.public import ProviderScanRoot, ProviderScanSource


class _Provider:
    async def list_path(self, path: str, refresh: bool = False, strict: bool = False):
        return []

    async def get_metadata(self, path: str):
        return {"name": path.rsplit("/", 1)[-1]}


class _Adapter:
    def __init__(self, provider, roots) -> None:
        self.provider = provider
        self.roots = roots
        self.last_scan_metrics: dict[str, int] = {}
        self.last_scan_run_id: str | None = "run-1"
        self.durable_session = None

    def set_durable_session(self, session) -> None:
        self.durable_session = session


class _StateSession:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def commit(self) -> None:
        self.events.append("state_commit")

    async def rollback(self) -> None:
        self.events.append("state_rollback")


class _IndexSession:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def commit(self) -> None:
        self.events.append("index_commit")


def _source() -> ProviderScanSource:
    root = ProviderScanRoot(
        root_mapping_id=9,
        content_type="software",
        display_name="Apps",
        storage_path="/apps",
    )
    return ProviderScanSource(provider=_Provider(), roots=(root,))


def _success_result() -> dict:
    return {
        "status": "success",
        "engine": "v2",
        "scan_complete": True,
        "categories_scanned": 1,
        "pages_fetched": 1,
        "writes": {
            "added": 1,
            "changed": 0,
            "renamed": 0,
            "moved": 0,
            "removed": 0,
            "unchanged": 2,
            "conflict": 0,
        },
        "suppressed_removals": 0,
        "errors": [],
    }


async def _run(monkeypatch, *, seed_fails: bool):
    events: list[str] = []
    logs: list[tuple[str, str, str, str | None]] = []

    async def fake_sources(_state):
        return [_source()]

    @asynccontextmanager
    async def fake_state_session():
        yield _StateSession(events)

    @asynccontextmanager
    async def fake_index_session():
        yield _IndexSession(events)

    async def fake_run_indexing_v2(**_kwargs):
        return _success_result()

    async def fake_seed(session, *, root_mapping_id, run_id, verified_at=None):
        assert isinstance(session, _StateSession)
        assert root_mapping_id == 9
        assert run_id == "run-1"
        assert verified_at is None
        events.append("baseline_seed")
        if seed_fails:
            raise RuntimeError("baseline boom")
        return 4

    async def fake_status(*_args, **_kwargs):
        return None

    async def fake_log(module, action, message, level="INFO"):
        logs.append((module, action, message, level))

    monkeypatch.setattr(provider_public, "enabled_provider_scan_sources", fake_sources)
    monkeypatch.setattr(platform_db, "state_session", fake_state_session)
    monkeypatch.setattr(platform_db, "index_session", fake_index_session)
    monkeypatch.setattr(alist_adapter, "AListProviderAdapter", _Adapter)
    monkeypatch.setattr(legacy_bridge, "run_indexing_v2", fake_run_indexing_v2)
    monkeypatch.setattr(legacy_bridge, "_durable_scan_enabled", lambda: True)
    monkeypatch.setattr(legacy_bridge, "_update_v2_sync_status", fake_status)
    monkeypatch.setattr(legacy_bridge, "_log_operation", fake_log)
    monkeypatch.setattr(
        baseline_module,
        "seed_verification_baseline_from_durable_run",
        fake_seed,
    )

    result = await legacy_bridge.run_indexing_v2_production(
        store_factory=lambda _session: object(),
    )
    return result, events, logs


async def test_baseline_is_seeded_only_after_index_commit(monkeypatch) -> None:
    result, events, logs = await _run(monkeypatch, seed_fails=False)

    assert result["status"] == "success"
    assert result["scan_complete"] is True
    assert events.index("index_commit") < events.index("baseline_seed")
    assert events.index("baseline_seed") < events.index("state_commit")
    assert "state_rollback" not in events
    assert any(
        action == "v2_verification_baseline_seeded"
        and "directories=4" in message
        for _, action, message, _ in logs
    )


async def test_baseline_failure_warns_without_rewriting_success(monkeypatch) -> None:
    result, events, logs = await _run(monkeypatch, seed_fails=True)

    assert result["status"] == "success"
    assert result["scan_complete"] is True
    assert result["errors"] == []
    assert events.index("index_commit") < events.index("baseline_seed")
    assert "state_rollback" in events
    assert any(
        action == "v2_verification_baseline_failed"
        and level == "WARNING"
        and "baseline boom" in message
        for _, action, message, level in logs
    )
    assert not any(
        action == "v2_verification_baseline_seeded"
        for _, action, _, _ in logs
    )
