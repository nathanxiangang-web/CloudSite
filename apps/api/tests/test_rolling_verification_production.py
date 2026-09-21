"""Production composition tests for one-shot R8 verification."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass

from cloudsite.modules.providers.contracts.public import ProviderScanRoot, ProviderScanSource
from cloudsite.tasks import sync as sync_tasks


class _Context(AbstractAsyncContextManager):
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _State:
    def __init__(self, name: str, events: list[str]):
        self.name = name
        self.events = events

    async def commit(self):
        self.events.append(f"{self.name}:commit")

    async def rollback(self):
        self.events.append(f"{self.name}:rollback")


class _Provider:
    async def list_path(self, path, refresh=False, strict=False):
        return []

    async def get_metadata(self, path):
        return {"name": path.rsplit("/", 1)[-1]}


@dataclass
class _Summary:
    root_mapping_id: int
    status: str
    selected: int = 1
    checked: int = 1
    unchanged: int = 1
    dirty: int = 0
    failed: int = 0
    dirty_paths: list[str] | None = None
    failed_paths: list[str] | None = None
    errors: list[str] | None = None

    def __post_init__(self):
        self.dirty_paths = self.dirty_paths or []
        self.failed_paths = self.failed_paths or []
        self.errors = self.errors or []


async def test_run_rolling_verification_once_isolates_root_transactions(monkeypatch):
    events: list[str] = []
    provider = _Provider()
    roots = (
        ProviderScanRoot(1, "software", "A", "/a"),
        ProviderScanRoot(2, "software", "B", "/b"),
    )
    source = ProviderScanSource(provider=provider, roots=roots)

    async def fake_sources(_state):
        return [source]

    sessions = iter(
        [
            _State("source", events),
            _State("root1", events),
            _State("root2", events),
        ]
    )

    monkeypatch.setattr(
        sync_tasks,
        "state_session",
        lambda: _Context(next(sessions)),
    )
    monkeypatch.setattr(
        sync_tasks,
        "enabled_provider_scan_sources",
        fake_sources,
    )

    class _Service:
        def __init__(self, *, batch_size):
            assert batch_size == 7

        async def verify_root(
            self,
            *,
            provider,
            root,
            verification_state,
            dirty_scopes,
        ):
            assert provider is source.provider
            if root.root_mapping_id == 2:
                raise RuntimeError("root two failed")
            return _Summary(root_mapping_id=1, status="success")

    monkeypatch.setattr(sync_tasks, "RollingVerificationService", _Service)

    result = await sync_tasks.run_rolling_verification_once(batch_size=7)

    assert result["status"] == "partial"
    assert [root["status"] for root in result["roots"]] == ["success", "failed"]
    assert len(result["errors"]) == 1
    assert "root two failed" in result["errors"][0]
    assert events == ["root1:commit", "root2:rollback"]


async def test_run_rolling_verification_once_reports_all_baselines_missing(monkeypatch):
    provider = _Provider()
    source = ProviderScanSource(
        provider=provider,
        roots=(ProviderScanRoot(3, "software", "C", "/c"),),
    )

    async def fake_sources(_state):
        return [source]

    states = iter([_State("source", []), _State("root", [])])
    monkeypatch.setattr(sync_tasks, "state_session", lambda: _Context(next(states)))
    monkeypatch.setattr(sync_tasks, "enabled_provider_scan_sources", fake_sources)

    class _Service:
        def __init__(self, *, batch_size):
            pass

        async def verify_root(self, **_kwargs):
            return _Summary(
                root_mapping_id=3,
                status="baseline_required",
                selected=0,
                checked=0,
                unchanged=0,
            )

    monkeypatch.setattr(sync_tasks, "RollingVerificationService", _Service)

    result = await sync_tasks.run_rolling_verification_once()

    assert result["status"] == "baseline_required"
    assert result["roots"][0]["status"] == "baseline_required"
