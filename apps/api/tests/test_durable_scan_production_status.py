"""Production durable-scan status regression tests."""

from __future__ import annotations

from contextlib import asynccontextmanager

import cloudsite.modules.indexing.infrastructure.alist_adapter as alist_adapter
import cloudsite.modules.indexing.infrastructure.legacy_bridge as legacy_bridge
import cloudsite.modules.providers.contracts.public as provider_public
import cloudsite.platform.db as platform_db
from cloudsite.modules.providers.contracts.public import ProviderScanRoot, ProviderScanSource


class _FakeProvider:
    async def list_path(self, path: str, refresh: bool = False, strict: bool = False):
        return []

    async def get_metadata(self, path: str):
        return {"name": path.rsplit("/", 1)[-1]}


class _FakeAdapter:
    instances: list["_FakeAdapter"] = []

    def __init__(self, provider, roots) -> None:
        self.provider = provider
        self.roots = roots
        self.last_scan_metrics: dict[str, int] = {}
        self.durable_sessions: list[object | None] = []
        type(self).instances.append(self)

    def set_durable_session(self, session) -> None:
        self.durable_sessions.append(session)


class _FakeIndexSession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


async def test_durable_incomplete_scan_finishes_as_failed_admin_status(monkeypatch) -> None:
    """Incomplete durable production scans must never look successful externally."""

    root = ProviderScanRoot(
        root_mapping_id=7,
        content_type="software",
        display_name="Apps",
        storage_path="/apps",
    )
    source = ProviderScanSource(provider=_FakeProvider(), roots=(root,))

    async def fake_enabled_provider_scan_sources(_state):
        return [source]

    state_tokens: list[object] = []

    @asynccontextmanager
    async def fake_state_session():
        token = object()
        state_tokens.append(token)
        yield token

    index_sessions: list[_FakeIndexSession] = []

    @asynccontextmanager
    async def fake_index_session():
        session = _FakeIndexSession()
        index_sessions.append(session)
        yield session

    async def fake_run_indexing_v2(**_kwargs):
        return {
            "status": "success",
            "engine": "v2",
            "scan_complete": False,
            "categories_scanned": 1,
            "pages_fetched": 1,
            "writes": {
                "added": 1,
                "changed": 0,
                "renamed": 0,
                "moved": 0,
                "removed": 0,
                "unchanged": 1,
                "conflict": 0,
            },
            "suppressed_removals": 1,
            "errors": [],
        }

    status_calls: list[str] = []
    log_calls: list[tuple[str, str, str]] = []

    async def fake_update_status(status, *_args, **_kwargs):
        status_calls.append(status)

    async def fake_log_operation(module, action, message, **_kwargs):
        log_calls.append((module, action, message))

    monkeypatch.setattr(
        provider_public,
        "enabled_provider_scan_sources",
        fake_enabled_provider_scan_sources,
    )
    monkeypatch.setattr(platform_db, "state_session", fake_state_session)
    monkeypatch.setattr(platform_db, "index_session", fake_index_session)
    monkeypatch.setattr(alist_adapter, "AListProviderAdapter", _FakeAdapter)
    monkeypatch.setattr(legacy_bridge, "run_indexing_v2", fake_run_indexing_v2)
    monkeypatch.setattr(legacy_bridge, "_durable_scan_enabled", lambda: True)
    monkeypatch.setattr(legacy_bridge, "_update_v2_sync_status", fake_update_status)
    monkeypatch.setattr(legacy_bridge, "_log_operation", fake_log_operation)

    _FakeAdapter.instances.clear()

    result = await legacy_bridge.run_indexing_v2_production(
        store_factory=lambda _session: object(),
    )

    assert result["status"] == "partial"
    assert result["scan_complete"] is False
    assert result["writes"]["removed"] == 0
    assert result["suppressed_removals"] == 1
    assert result["errors"] == [
        "/apps(software): durable scan incomplete; removals suppressed"
    ]

    # Public/Admin-facing progress must end failed, not completed.
    assert status_calls[0] == "running"
    assert status_calls[-1] == "failed"
    assert "completed" not in status_calls[-1:]

    # The successful reconcile transaction may commit non-destructive writes,
    # but the root is still promoted to partial at the production boundary.
    assert index_sessions and index_sessions[0].commits == 1

    # Durable state is attached only around the root execution and always detached.
    assert len(_FakeAdapter.instances) == 1
    adapter = _FakeAdapter.instances[0]
    assert len(adapter.durable_sessions) == 2
    assert adapter.durable_sessions[0] in state_tokens
    assert adapter.durable_sessions[-1] is None

    assert any(action == "v2_category_partial" for _, action, _ in log_calls)
    assert any(action == "v2_sync_failed" for _, action, _ in log_calls)
