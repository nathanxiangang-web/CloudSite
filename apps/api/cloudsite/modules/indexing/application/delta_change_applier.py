"""Delta change applier (V2 doc section 27).

Bridges the providers-side lightweight ProviderChange (from
providers.domain.delta) to the indexing-side ProviderChange (from
indexing.domain.provider_change) and dispatches each change to a
sink for application to the index.

This class produces the ``apply_changes`` callback required by
``DeltaSyncStrategy``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..domain.provider_change import (
    ProviderChange as IndexingProviderChange,
    ProviderChangeSource,
    ProviderChangeType,
)


@runtime_checkable
class ChangeSink(Protocol):
    """Sink for applying provider changes to the index."""

    async def upsert_entry(self, path: str, is_dir: bool, provider_object_id: str | None) -> None: ...

    async def remove_entry(self, path: str) -> None: ...

    async def rename_entry(self, old_path: str, new_path: str, is_dir: bool) -> None: ...

    async def mark_directory_dirty(self, path: str) -> None: ...


_CHANGE_TYPE_MAP: dict[str, ProviderChangeType] = {
    "create": ProviderChangeType.CREATE,
    "update": ProviderChangeType.UPDATE,
    "delete": ProviderChangeType.DELETE,
    "rename": ProviderChangeType.RENAME,
    "move": ProviderChangeType.MOVE,
    "directory_dirty": ProviderChangeType.DIRECTORY_DIRTY,
}


@dataclass(frozen=True, slots=True)
class ApplyResult:
    """Outcome of applying a batch of provider changes."""

    applied: int
    failed: int
    skipped: int
    errors: list[str]

    @property
    def success(self) -> bool:
        return self.failed == 0


class DeltaChangeApplier:
    """Convert and apply provider delta changes to the index.

    Wraps a ChangeSink and produces the ``apply_changes`` callback
    for ``DeltaSyncStrategy``.  Each lightweight ProviderChange from
    the provider is converted to an indexing-side ProviderChange with
    ``source=PROVIDER_DELTA`` and dispatched to the sink.
    """

    def __init__(self, root_mapping_id: int, sink: ChangeSink) -> None:
        self._root_mapping_id = root_mapping_id
        self._sink = sink

    def _convert(self, change) -> IndexingProviderChange:
        change_type = _CHANGE_TYPE_MAP.get(change.change_type)
        if change_type is None:
            raise ValueError(f"unknown change_type: {change.change_type!r}")

        path = change.path or ""
        return IndexingProviderChange(
            change_type=change_type,
            root_mapping_id=self._root_mapping_id,
            path=path,
            is_dir=change.is_dir or False,
            provider_object_id=change.provider_object_id,
            old_path=change.old_path,
            source=ProviderChangeSource.PROVIDER_DELTA,
        )

    async def apply(self, changes: list) -> bool:
        """Apply a batch of provider changes. Returns True if all succeeded."""
        result = await self.apply_detailed(changes)
        return result.success

    async def apply_detailed(self, changes: list) -> ApplyResult:
        """Apply changes and return detailed result."""
        applied = 0
        failed = 0
        skipped = 0
        errors: list[str] = []

        for change in changes:
            try:
                idx_change = self._convert(change)
            except ValueError as exc:
                failed += 1
                errors.append(str(exc))
                continue

            try:
                if idx_change.change_type is ProviderChangeType.CREATE:
                    await self._sink.upsert_entry(
                        idx_change.path,
                        idx_change.is_dir,
                        idx_change.provider_object_id,
                    )
                elif idx_change.change_type is ProviderChangeType.UPDATE:
                    await self._sink.upsert_entry(
                        idx_change.path,
                        idx_change.is_dir,
                        idx_change.provider_object_id,
                    )
                elif idx_change.change_type is ProviderChangeType.DELETE:
                    await self._sink.remove_entry(idx_change.path)
                elif idx_change.change_type in (
                    ProviderChangeType.RENAME,
                    ProviderChangeType.MOVE,
                ):
                    if not idx_change.old_path:
                        skipped += 1
                        continue
                    await self._sink.rename_entry(
                        idx_change.old_path,
                        idx_change.path,
                        idx_change.is_dir,
                    )
                elif idx_change.change_type is ProviderChangeType.DIRECTORY_DIRTY:
                    await self._sink.mark_directory_dirty(idx_change.path)
                else:
                    skipped += 1
                    continue
                applied += 1
            except Exception as exc:
                failed += 1
                errors.append(f"{idx_change.path}: {exc}")

        return ApplyResult(applied=applied, failed=failed, skipped=skipped, errors=errors)

    def as_callback(self):
        """Return the apply function as a callback for DeltaSyncStrategy."""
        return self.apply


__all__ = ["ChangeSink", "ApplyResult", "DeltaChangeApplier"]