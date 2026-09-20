"""Narrowly scoped AList single-file move helper.

Moves one file within one enabled ContentRootMapping. All paths are validated
against the exact mapping root with normalized segments; traversal, root move,
path ambiguity, same path, and destination outside the root are rejected.
The destination directory must already exist; no cross-mapping moves are issued.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cloudsite.alist import AListClient, AListError


@dataclass(frozen=True, slots=True)
class MoveResult:
    """Structured record returned by move_file_within_root."""

    source: str
    destination: str
    result: dict[str, Any]


def _normalize_segments(path: str, *, allow_root: bool = False) -> list[str]:
    if path == "/" and allow_root:
        return []
    if (
        not isinstance(path, str)
        or not path.startswith("/")
        or path == "/"
        or path.endswith("/")
        or "//" in path
        or "\\" in path
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in path)
    ):
        raise AListError("invalid absolute path", "AL-005", status_code=400)
    parts = path[1:].split("/")
    if any(part in {".", ".."} for part in parts):
        raise AListError("path contains illegal . or .. segment", "AL-005", status_code=400)
    return parts


def _join(parts: list[str]) -> str:
    return "/" + "/".join(parts) if parts else "/"


def _validate_under_root(
    path: str, root_parts: list[str], *, allow_root: bool
) -> list[str]:
    parts = _normalize_segments(path, allow_root=allow_root)
    if parts[: len(root_parts)] != root_parts:
        raise AListError("path is not under the content root", "AL-005", status_code=400)
    if not allow_root and len(parts) <= len(root_parts):
        raise AListError("cannot move the content root itself", "AL-005", status_code=400)
    return parts


async def move_file_within_root(
    client: AListClient,
    root: str,
    source_path: str,
    destination_dir: str,
) -> MoveResult:
    """Move one file within one ContentRootMapping root.

    Inputs:
        client: an existing AListClient instance.
        root: mapping.alist_path used as the containment root.
        source_path: full path of the file to move (must be strictly below root).
        destination_dir: full path of the destination directory
            (must be at or below root and already exist).

    The source name is confirmed via client.list_path(refresh=True, strict=True)
    on the source directory, and a target collision is rejected so the move
    never overwrites an existing destination file. The AList move API is called
    via client.move_file('POST', '/api/fs/move', ...); response
    code verification is performed by AListClient._request per existing behavior.
    """
    root_parts = _normalize_segments(root, allow_root=True)

    source_parts = _validate_under_root(source_path, root_parts, allow_root=False)
    destination_parts = _validate_under_root(
        destination_dir, root_parts, allow_root=True
    )

    filename = source_parts[-1]
    source_dir = _join(source_parts[:-1])
    destination_dir_normalized = _join(destination_parts)
    destination = _join(destination_parts + [filename])

    if destination == _join(source_parts):
        raise AListError("source path and destination path are the same", "AL-005", status_code=400)

    source_listing = await client.list_path(source_dir, refresh=True, strict=True)
    matched_entry: dict[str, Any] | None = None
    for entry in source_listing:
        if str(entry.get("name") or "") == filename:
            matched_entry = entry
            break
    if matched_entry is None:
        raise AListError("source file does not exist", "AL-005", status_code=404)
    if bool(matched_entry.get("is_dir")):
        raise AListError("source path is a directory, not a file", "AL-005", status_code=400)

    destination_listing = await client.list_path(
        destination_dir_normalized, refresh=True, strict=True
    )
    for entry in destination_listing:
        if str(entry.get("name") or "") == filename:
            raise AListError(
                "destination already has an object with the same name, refusing to overwrite",
                "AL-005",
                status_code=409,
            )

    payload = await client.move_file(
        source_dir=source_dir,
        destination_dir=destination_dir_normalized,
        names=[filename],
    )
    return MoveResult(
        source=_join(source_parts), destination=destination, result=payload
    )
