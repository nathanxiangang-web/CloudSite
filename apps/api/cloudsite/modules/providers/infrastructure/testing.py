from __future__ import annotations

from dataclasses import dataclass, field

from ..domain.delta import ProviderChange, ProviderCursorInvalid


@dataclass
class FakeDeltaProvider:
    journal: list[tuple[str, ProviderChange]] = field(default_factory=list)
    cursor: str = "0"
    invalid_after: int | None = None
    _emitted: int = 0

    def emit(self, change_type: str, *, path: str | None = None, old_path: str | None = None, is_dir: bool | None = None) -> "FakeDeltaProvider":
        self._emitted += 1
        self.journal.append((str(self._emitted), ProviderChange(change_type, path=path, old_path=old_path, is_dir=is_dir)))
        return self

    async def bootstrap_cursor(self) -> str:
        return self.cursor

    async def fetch_changes(self, cursor: str | None) -> tuple[list[ProviderChange], str]:
        consumed = int(cursor or "0")
        if self.invalid_after is not None and consumed >= self.invalid_after:
            raise ProviderCursorInvalid("cursor expired")
        batch = [change for position, change in self.journal if int(position) > consumed]
        return batch, str(self._emitted)


__all__ = ["FakeDeltaProvider"]