"""Durable production status contract regressions.

The deployment E2E intentionally restarts the API. These focused tests lock
the status semantics that can be verified without a real provider host:
an incomplete durable production scan must end in the persisted failed
state rather than being reported as a successful sync.
"""
from __future__ import annotations

from types import SimpleNamespace

from cloudsite.modules.indexing.infrastructure import legacy_bridge
from cloudsite.modules.providers.contracts import public as providers_public
from cloudsite.modules.providers.contracts.public import ProviderScanRoot
from cloudsite.platform import db as platform_db


class _AsyncContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


async def test_incomplete_durable_production_sync_finishes_failed(monkeypatch):
    root = ProviderScanRoot(
        root_mapping_id=7,
        storage_path="/provider-root",
        content_type="software",
        display_name="Provider Root",
    )
    source = SimpleNamespace(provider=object(), roots=(root,))

    async def fake_sources(_state):
        return [source]

    async def fake_run_indexing_v2(**kwargs):
        assert getattr(kwargs["adapter"], "_durable_session", None) is not None
        return {
            "status": "success",
            "engine": "v2",
            "scan_complete": False,
            "categories_scanned": 1,
            "pages_fetched": 1,
            "writes": {
                "added": 0,
                "changed": 0,
                "renamed": 0,
                "moved": 0,
                "removed": 0,
                "unchanged": 3,
                "conflict": 0,
            },
            "suppressed_removals": 2,
            "errors": [],
        }

    status_calls: list[str] = []

    async def fake_update_status(status, *args, **kwargs):
        status_calls.append(status)

    async def fake_log(*args, **kwargs):
        return None

    monkeypatch.setattr(
        providers_public,
        "enabled_provider_scan_sources",
        fake_sources,
    )
    monkeypatch.setattr(platform_db, "state_session", lambda: _AsyncContext())
    monkeypatch.setattr(platform_db, "index_session", lambda: _AsyncContext())
    monkeypatch.setattr(legacy_bridge, "run_indexing_v2", fake_run_indexing_v2)
    monkeypatch.setattr(legacy_bridge, "_update_v2_sync_status", fake_update_status)
    monkeypatch.setattr(legacy_bridge, "_log_operation", fake_log)
    monkeypatch.setattr(legacy_bridge, "_durable_scan_enabled", lambda: True)

    result = await legacy_bridge.run_indexing_v2_production(
        store_factory=lambda _session: object(),
    )

    assert result["status"] == "partial"
    assert result["scan_complete"] is False, result
    assert result["errors"]
    assert "durable scan incomplete" in result["errors"][0]
    assert status_calls[0] == "running"
    assert status_calls[-1] == "failed"
    assert "completed" not in status_calls
