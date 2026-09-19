"""Admin-facing Indexing helpers for legacy/manual sync compatibility."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ...providers.contracts.public import (
    list_root_mappings,
    normalize_provider_path,
)


MAX_MANUAL_PATHS = 50


async def validate_manual_sync_paths(
    state: AsyncSession,
    paths: list[str],
) -> tuple[list[str], list[dict[str, str]]]:
    """Validate manual paths against enabled provider root mappings.

    This is the module-side compatibility boundary for the legacy manual path
    orchestrator. The router receives plain strings/dicts and never sees
    Provider ORM models.
    """

    accepted: list[str] = []
    rejected: list[dict[str, str]] = []
    if len(paths) > MAX_MANUAL_PATHS:
        return [], [
            {
                "path": "",
                "reason": f"路径数量超过上限 {MAX_MANUAL_PATHS}",
            }
        ]

    mappings = await list_root_mappings(state)
    roots = [
        normalize_provider_path(str(mapping.get("alist_path") or ""))
        for mapping in mappings
        if bool(mapping.get("enabled"))
    ]

    for raw_path in paths:
        path = normalize_provider_path(raw_path)
        if ".." in path.split("/"):
            rejected.append(
                {"path": path, "reason": "路径包含非法的 .. 段"}
            )
            continue
        if any(
            path == root
            or path.startswith(root.rstrip("/") + "/")
            for root in roots
        ):
            accepted.append(path)
        else:
            rejected.append(
                {
                    "path": path,
                    "reason": "路径不在任何已启用内容根下",
                }
            )
    return accepted, rejected


__all__ = ["MAX_MANUAL_PATHS", "validate_manual_sync_paths"]
