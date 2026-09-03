"""Delta 同步契约与策略解析。

Generic AList 默认永远 Rolling；只有 Provider 明确声明
supports_delta + supports_change_cursor 时才启用 Delta。Cursor 只有在
本批 Change 全部安全 Commit 后才能推进；失败则保持原 cursor 供重放。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

from .capabilities import CapabilityState, ProviderCapabilities


@dataclass(frozen=True, slots=True)
class ProviderChange:
    change_type: str  # created | updated | deleted | moved | renamed | unknown
    provider_object_id: str | None = None
    path: str | None = None
    old_path: str | None = None
    is_dir: bool | None = None
    cursor: str | None = None


class ProviderCursorInvalid(RuntimeError):
    """上游 cursor 失效，必须回退到 Full Bootstrap / Rolling Verification。"""


@runtime_checkable
class SyncStrategy(Protocol):
    name: str

    async def bootstrap(self, *args: Any, **kwargs: Any) -> dict[str, Any]: ...
    async def sync_once(self, *args: Any, **kwargs: Any) -> dict[str, Any]: ...
    async def recover(self, *args: Any, **kwargs: Any) -> dict[str, Any]: ...


class RollingSyncStrategy:
    name = "rolling"

    async def bootstrap(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"strategy": self.name, "status": "delegated_to_rolling"}

    async def sync_once(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"strategy": self.name, "status": "delegated_to_rolling"}

    async def recover(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"strategy": self.name, "status": "delegated_to_rolling"}


def resolve_sync_strategy(capabilities: ProviderCapabilities) -> str:
    """根据显式 Capability 选择同步策略；默认 Rolling。"""
    if (
        capabilities.supports_delta is CapabilityState.YES
        and capabilities.supports_change_cursor is CapabilityState.YES
    ):
        return "delta"
    if (
        capabilities.supports_webhook is CapabilityState.YES
        and capabilities.supports_delta is CapabilityState.YES
    ):
        return "webhook_delta"
    return "rolling"


ApplyChanges = Callable[[list[ProviderChange]], Awaitable[bool]]


class DeltaSyncStrategy:
    """Cursor 事务模型：fetch → apply → commit → advance cursor。

    `apply_changes` 返回 False 表示本批未安全落地，cursor 保持原值供重放。
    `fetch_changes` 抛出 ProviderCursorInvalid 时回退到 Full Bootstrap。
    """

    name = "delta"

    def __init__(
        self,
        fetch_changes: Callable[[str | None], Awaitable[tuple[list[ProviderChange], str]]],
        apply_changes: ApplyChanges,
        load_cursor: Callable[[], Awaitable[str | None]],
        save_cursor: Callable[[str], Awaitable[None]],
        mark_invalid: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._fetch_changes = fetch_changes
        self._apply_changes = apply_changes
        self._load_cursor = load_cursor
        self._save_cursor = save_cursor
        self._mark_invalid = mark_invalid

    async def bootstrap(self) -> dict[str, Any]:
        # Delta Bootstrap 必须先从一致性快照取得 cursor，再开始接 Change。
        cursor = await self._load_cursor()
        if cursor is None:
            return {"strategy": self.name, "status": "bootstrap_required"}
        return {"strategy": self.name, "status": "bootstrapped", "cursor": cursor}

    async def sync_once(self) -> dict[str, Any]:
        cursor = await self._load_cursor()
        try:
            changes, next_cursor = await self._fetch_changes(cursor)
        except ProviderCursorInvalid:
            if self._mark_invalid is not None:
                await self._mark_invalid()
            return {"strategy": self.name, "status": "cursor_invalid", "fallback": "rolling"}

        applied = await self._apply_changes(changes)
        if not applied:
            return {"strategy": self.name, "status": "failed", "cursor": cursor, "replayed": False}

        await self._save_cursor(next_cursor)
        return {"strategy": self.name, "status": "success", "cursor": next_cursor, "applied": len(changes)}

    async def recover(self) -> dict[str, Any]:
        return {"strategy": self.name, "status": "recover_requires_bootstrap"}
