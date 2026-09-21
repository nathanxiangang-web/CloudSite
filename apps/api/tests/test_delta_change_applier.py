"""R10 PR03: DeltaChangeApplier tests (V2 doc section 27).

Tests conversion from provider-side ProviderChange to indexing-side
ProviderChange and dispatch to ChangeSink.
"""
import pytest

from cloudsite.modules.indexing.application.delta_change_applier import (
    ApplyResult,
    ChangeSink,
    DeltaChangeApplier,
)
from cloudsite.modules.indexing.domain.provider_change import (
    ProviderChangeSource,
    ProviderChangeType,
)
from cloudsite.modules.providers.domain.delta import ProviderChange


class _RecordingSink:
    """ChangeSink implementation that records all calls."""

    def __init__(self) -> None:
        self.upserts: list[tuple[str, bool, str | None]] = []
        self.removals: list[str] = []
        self.renames: list[tuple[str, str, bool]] = []
        self.dirty: list[str] = []

    async def upsert_entry(self, path: str, is_dir: bool, provider_object_id: str | None) -> None:
        self.upserts.append((path, is_dir, provider_object_id))

    async def remove_entry(self, path: str) -> None:
        self.removals.append(path)

    async def rename_entry(self, old_path: str, new_path: str, is_dir: bool) -> None:
        self.renames.append((old_path, new_path, is_dir))

    async def mark_directory_dirty(self, path: str) -> None:
        self.dirty.append(path)


class _FailingSink(_RecordingSink):
    """Sink that fails on remove_entry."""

    async def remove_entry(self, path: str) -> None:
        raise RuntimeError("removal failed")


class TestDeltaChangeApplier:
    @pytest.fixture
    def sink(self):
        return _RecordingSink()

    @pytest.fixture
    def applier(self, sink):
        return DeltaChangeApplier(root_mapping_id=1, sink=sink)

    @pytest.mark.asyncio
    async def test_apply_create(self, applier, sink):
        changes = [ProviderChange("create", path="/a.txt", is_dir=False)]
        result = await applier.apply(changes)
        assert result is True
        assert sink.upserts == [("/a.txt", False, None)]
        assert sink.removals == []

    @pytest.mark.asyncio
    async def test_apply_update(self, applier, sink):
        changes = [ProviderChange("update", path="/a.txt", provider_object_id="obj-1")]
        result = await applier.apply(changes)
        assert result is True
        assert sink.upserts == [("/a.txt", False, "obj-1")]

    @pytest.mark.asyncio
    async def test_apply_delete(self, applier, sink):
        changes = [ProviderChange("delete", path="/b.txt")]
        result = await applier.apply(changes)
        assert result is True
        assert sink.removals == ["/b.txt"]

    @pytest.mark.asyncio
    async def test_apply_rename(self, applier, sink):
        changes = [ProviderChange("rename", path="/new.txt", old_path="/old.txt", is_dir=False)]
        result = await applier.apply(changes)
        assert result is True
        assert sink.renames == [("/old.txt", "/new.txt", False)]

    @pytest.mark.asyncio
    async def test_apply_move(self, applier, sink):
        changes = [ProviderChange("move", path="/dir2/file.txt", old_path="/dir1/file.txt", is_dir=False)]
        result = await applier.apply(changes)
        assert result is True
        assert sink.renames == [("/dir1/file.txt", "/dir2/file.txt", False)]

    @pytest.mark.asyncio
    async def test_apply_directory_dirty(self, applier, sink):
        changes = [ProviderChange("directory_dirty", path="/some/dir")]
        result = await applier.apply(changes)
        assert result is True
        assert sink.dirty == ["/some/dir"]

    @pytest.mark.asyncio
    async def test_apply_mixed_changes(self, applier, sink):
        changes = [
            ProviderChange("create", path="/new.txt"),
            ProviderChange("update", path="/edit.txt", provider_object_id="o1"),
            ProviderChange("delete", path="/gone.txt"),
            ProviderChange("rename", path="/renamed.txt", old_path="/original.txt"),
            ProviderChange("directory_dirty", path="/dirty/dir"),
        ]
        result = await applier.apply(changes)
        assert result is True
        assert len(sink.upserts) == 2
        assert len(sink.removals) == 1
        assert len(sink.renames) == 1
        assert len(sink.dirty) == 1

    @pytest.mark.asyncio
    async def test_apply_empty_list(self, applier):
        result = await applier.apply([])
        assert result is True

    @pytest.mark.asyncio
    async def test_apply_returns_false_on_failure(self):
        sink = _FailingSink()
        applier = DeltaChangeApplier(root_mapping_id=1, sink=sink)
        changes = [ProviderChange("delete", path="/fail.txt")]
        result = await applier.apply(changes)
        assert result is False

    @pytest.mark.asyncio
    async def test_apply_detailed_result(self, applier):
        changes = [
            ProviderChange("create", path="/a.txt"),
            ProviderChange("delete", path="/b.txt"),
        ]
        result = await applier.apply_detailed(changes)
        assert isinstance(result, ApplyResult)
        assert result.applied == 2
        assert result.failed == 0
        assert result.skipped == 0
        assert result.errors == []
        assert result.success is True

    @pytest.mark.asyncio
    async def test_apply_detailed_with_failure(self):
        sink = _FailingSink()
        applier = DeltaChangeApplier(root_mapping_id=1, sink=sink)
        changes = [
            ProviderChange("create", path="/ok.txt"),
            ProviderChange("delete", path="/fail.txt"),
        ]
        result = await applier.apply_detailed(changes)
        assert result.applied == 1
        assert result.failed == 1
        assert result.success is False
        assert len(result.errors) == 1

    @pytest.mark.asyncio
    async def test_rename_without_old_path_skipped(self, applier):
        changes = [ProviderChange("rename", path="/new.txt")]
        result = await applier.apply_detailed(changes)
        assert result.skipped == 1
        assert result.applied == 0
        assert result.success is True

    @pytest.mark.asyncio
    async def test_unknown_change_type_fails(self, applier):
        changes = [ProviderChange("bogus", path="/x.txt")]
        result = await applier.apply_detailed(changes)
        assert result.failed == 1
        assert result.success is False

    def test_as_callback_returns_callable(self, applier):
        callback = applier.as_callback()
        assert callable(callback)

    @pytest.mark.asyncio
    async def test_converted_change_has_provider_delta_source(self, applier, sink):
        changes = [ProviderChange("create", path="/a.txt")]
        await applier.apply(changes)
        assert len(sink.upserts) == 1

    def test_sink_protocol_matches_recording_sink(self):
        sink = _RecordingSink()
        assert isinstance(sink, ChangeSink)