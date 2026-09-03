"""仅测试使用的 FakeDeltaProvider。

用它证明 Delta Strategy 架构真的工作（cursor 事务、重放、回退），
而不依赖真实第三方服务。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .delta import ProviderChange, ProviderCursorInvalid


@dataclass
class FakeDeltaProvider:
    """内存版 Delta Provider：journal 按 cursor 顺序存放 Change。"""

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
        # cursor 表示“已消费到哪一位”；fetch 返回其后尚未消费的 Change，
        # 不消费它们——消费只在 DeltaSyncStrategy 成功 commit 后通过 save_cursor 发生。
        consumed = int(cursor or "0")
        if self.invalid_after is not None and consumed >= self.invalid_after:
            raise ProviderCursorInvalid("cursor expired")
        batch = [change for position, change in self.journal if int(position) > consumed]
        return batch, str(self._emitted)
