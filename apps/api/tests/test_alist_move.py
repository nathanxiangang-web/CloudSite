"""Focused mocked tests for the AList single-file move helper.

No real AList access: all client methods are stubbed.
"""
from typing import Any

import pytest

from cloudsite.alist import AListError
from cloudsite.plugins.ai.services.alist_move import MoveResult, move_file_within_root


class _MockClient:
    """Minimal AListClient stand-in for move helper tests."""

    def __init__(
        self,
        listings: dict[str, list[dict[str, Any]]] | None = None,
        move_payload: dict[str, Any] | None = None,
        move_error: Exception | None = None,
    ) -> None:
        self._listings = listings or {}
        self._move_payload = move_payload or {
            "code": 200,
            "message": "success",
            "data": None,
        }
        self._move_error = move_error
        self.list_calls: list[tuple[str, bool, bool]] = []
        self.move_calls: list[dict[str, Any]] = []

    async def list_path(
        self, path: str, refresh: bool = False, strict: bool = False
    ) -> list[dict[str, Any]]:
        self.list_calls.append((path, refresh, strict))
        return self._listings.get(path, [])

    async def _authenticated_request(
        self, method: str, path: str, **kwargs: Any
    ) -> dict[str, Any]:
        self.move_calls.append({"method": method, "path": path, "kwargs": kwargs})
        if self._move_error is not None:
            raise self._move_error
        return self._move_payload


async def test_move_success() -> None:
    client = _MockClient(
        {
            "/root/src": [{"name": "file.txt", "is_dir": False}],
            "/root/dst": [{"name": "other.txt", "is_dir": False}],
        }
    )
    result = await move_file_within_root(
        client, "/root", "/root/src/file.txt", "/root/dst"
    )
    assert isinstance(result, MoveResult)
    assert result.source == "/root/src/file.txt"
    assert result.destination == "/root/dst/file.txt"
    assert result.result["code"] == 200
    assert len(client.move_calls) == 1
    call = client.move_calls[0]
    assert call["method"] == "POST"
    assert call["path"] == "/api/fs/move"
    assert call["kwargs"]["json"] == {
        "src_dir": "/root/src",
        "dst_dir": "/root/dst",
        "names": ["file.txt"],
    }
    assert all(ref and strict for _, ref, strict in client.list_calls)


async def test_move_path_escape_rejected() -> None:
    client = _MockClient()
    with pytest.raises(AListError, match="illegal"):
        await move_file_within_root(
            client, "/root", "/root/../escape/file.txt", "/root/dst"
        )
    assert client.move_calls == []


async def test_move_destination_escape_rejected() -> None:
    client = _MockClient()
    with pytest.raises(AListError, match="not under"):
        await move_file_within_root(
            client, "/root", "/root/src/file.txt", "/outside/dst"
        )
    assert client.move_calls == []


async def test_move_root_move_rejected() -> None:
    client = _MockClient()
    with pytest.raises(AListError, match="root itself"):
        await move_file_within_root(client, "/root", "/root", "/root/dst")
    assert client.move_calls == []


async def test_move_same_path_rejected() -> None:
    client = _MockClient()
    with pytest.raises(AListError, match="same"):
        await move_file_within_root(
            client, "/root", "/root/src/file.txt", "/root/src"
        )
    assert client.move_calls == []


async def test_move_collision_rejected() -> None:
    client = _MockClient(
        {
            "/root/src": [{"name": "file.txt", "is_dir": False}],
            "/root/dst": [{"name": "file.txt", "is_dir": False}],
        }
    )
    with pytest.raises(AListError, match="overwrite"):
        await move_file_within_root(
            client, "/root", "/root/src/file.txt", "/root/dst"
        )
    assert client.move_calls == []


async def test_move_missing_source_rejected() -> None:
    client = _MockClient(
        {
            "/root/src": [{"name": "other.txt", "is_dir": False}],
            "/root/dst": [],
        }
    )
    with pytest.raises(AListError, match="does not exist"):
        await move_file_within_root(
            client, "/root", "/root/src/file.txt", "/root/dst"
        )
    assert client.move_calls == []


async def test_move_source_is_directory_rejected() -> None:
    client = _MockClient(
        {
            "/root/src": [{"name": "subdir", "is_dir": True}],
            "/root/dst": [],
        }
    )
    with pytest.raises(AListError, match="directory"):
        await move_file_within_root(
            client, "/root", "/root/src/subdir", "/root/dst"
        )
    assert client.move_calls == []


async def test_move_api_failure_propagated() -> None:
    client = _MockClient(
        listings={
            "/root/src": [{"name": "file.txt", "is_dir": False}],
            "/root/dst": [],
        },
        move_error=AListError("AList internal error", "AL-005", status_code=502),
    )
    with pytest.raises(AListError, match="internal error"):
        await move_file_within_root(
            client, "/root", "/root/src/file.txt", "/root/dst"
        )
    assert len(client.move_calls) == 1


async def test_move_destination_at_root_allowed() -> None:
    client = _MockClient(
        {
            "/root/src": [{"name": "file.txt", "is_dir": False}],
            "/root": [{"name": "existing.txt", "is_dir": False}],
        }
    )
    result = await move_file_within_root(
        client, "/root", "/root/src/file.txt", "/root"
    )
    assert result.destination == "/root/file.txt"
    assert len(client.move_calls) == 1


async def test_move_with_root_mapping_at_slash() -> None:
    client = _MockClient({
        "/src": [{"name": "file.txt", "is_dir": False}],
        "/dst": [],
    })
    result = await move_file_within_root(client, "/", "/src/file.txt", "/dst")
    assert result.destination == "/dst/file.txt"
    assert len(client.move_calls) == 1


async def test_move_empty_source_rejected() -> None:
    client = _MockClient()
    with pytest.raises(AListError):
        await move_file_within_root(client, "/root", "", "/root/dst")
    assert client.move_calls == []


@pytest.mark.parametrize("root,source,destination", [
    ("/root/", "/root/src/file.txt", "/root/dst"),
    ("/root", "/root//src/file.txt", "/root/dst"),
    ("/root", "/root/src\\file.txt", "/root/dst"),
    ("/root", "root/src/file.txt", "/root/dst"),
    ("/root", "/root/src/file.txt", "/root/dst/"),
    ("/root", "/root/src/file.txt", "/root/dst\x00evil"),
])
async def test_move_rejects_ambiguous_paths(root, source, destination) -> None:
    client = _MockClient()
    with pytest.raises(AListError):
        await move_file_within_root(client, root, source, destination)
    assert client.move_calls == []
