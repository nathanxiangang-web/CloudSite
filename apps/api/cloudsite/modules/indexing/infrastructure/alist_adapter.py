"""AList ProviderAdapter for v2 indexing engine.

Implements the ProviderAdapter Protocol by wrapping AListClient.list_path
to recursively scan AList directories and produce SnapshotEntry lists.
Each entry carries persistence-neutral resource metadata. Parent IDs are resolved
inside Indexing before crossing the Resources contract boundary.
"""
from __future__ import annotations

import mimetypes
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, Protocol

from cloudsite.alist import AListClient
from cloudsite.indexer import normalize_path, join_path, should_ignore, stable_id, parse_time

from ..domain.inspection import InspectionRequest, InspectionResult
from ..domain.snapshot import SnapshotEntry
from .provider_adapter import ProviderCapabilities


class ContentRootView(Protocol):
    id: int
    content_type: str
    alist_path: str
    display_name: str


class AListProviderAdapter:
    """Production ProviderAdapter backed by AListClient."""

    def __init__(self, client: AListClient, roots: list[ContentRootView]) -> None:
        self._client = client
        self._roots = {str(root.id): root for root in roots}

    @property
    def provider_id(self) -> str:
        return "generic_alist"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_scan=True,
            supports_pagination=False,
            supports_inspect=True,
            supports_recursive_list=True,
        )

    async def scan_category(
        self,
        category_id: str,
        *,
        cursor: str | None = None,
        limit: int | None = None,
        on_progress: Any = None,
    ) -> tuple[list[SnapshotEntry], str | None, bool]:
        root = self._roots.get(category_id)
        if root is None:
            return [], None, True

        entries: list[SnapshotEntry] = []
        root_path = normalize_path(root.alist_path)
        root_id = stable_id("folder", root_path)
        entries.append(self._make_entry(
            resource_id=root_id,
            path=root_path,
            name=PurePosixPath(root_path).name or root.display_name,
            is_dir=True,
            modified=None,
            root=root,
            parent_path=None,
        ))

        queue: list[str] = [root_path]
        while queue:
            current_path = queue.pop(0)
            items = await self._client.list_path(current_path)
            if on_progress:
                await on_progress(current_path, len(entries))
            for item in items:
                name = str(item.get("name") or "").strip()
                if not name:
                    continue
                item_path = join_path(current_path, name)
                if should_ignore(item_path):
                    continue
                is_dir = bool(item.get("is_dir"))
                modified = parse_time(item.get("modified") or item.get("updated_at"))
                kind = "folder" if is_dir else "resource"
                entry = self._make_entry(
                    resource_id=stable_id(kind, item_path),
                    path=item_path,
                    name=name,
                    is_dir=is_dir,
                    modified=modified,
                    root=root,
                    parent_path=current_path,
                    item=item,
                )
                entries.append(entry)
                if is_dir:
                    queue.append(item_path)

        return entries, None, True

    async def inspect(self, request: InspectionRequest) -> InspectionResult:
        info = await self._client.get_file_info(request.path)
        return InspectionResult(
            resource_id=request.resource_id,
            path=request.path,
            name=info.get("name", ""),
            size=info.get("size"),
            modified_at=parse_time(info.get("modified")),
            metadata=info,
        )

    @staticmethod
    def _make_entry(
        *,
        resource_id: str,
        path: str,
        name: str,
        is_dir: bool,
        modified: datetime | None,
        root: ContentRootView,
        parent_path: str | None,
        item: dict[str, Any] | None = None,
    ) -> SnapshotEntry:
        item = item or {}
        ext = PurePosixPath(name).suffix.lower().lstrip(".") if not is_dir else ""
        mime = ""
        if not is_dir:
            mime = str(item.get("type") or mimetypes.guess_type(name)[0] or "application/octet-stream")
        return SnapshotEntry(
            resource_id=resource_id,
            path=path,
            name=name,
            size=int(item.get("size") or 0) if not is_dir else None,
            modified_at=modified,
            content_hash=None,
            metadata={
                "is_dir": is_dir,
                "content_type": root.content_type,
                "root_mapping_id": root.id,
                "parent_path": parent_path,
                "parent_id": stable_id("folder", parent_path) if parent_path else None,
                "extension": ext,
                "mime_type": mime,
                "thumbnail": str(item.get("thumb") or item.get("thumbnail") or ""),
            },
        )


__all__ = ["AListProviderAdapter"]