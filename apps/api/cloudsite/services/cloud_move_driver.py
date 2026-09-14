"""Cloud move driver: narrow async adapter for moving one existing file
within the fixed 115driver cloud-download folder.

Moves a single file from below /U+4E91 U+4E0B U+8F7D into a destination
subdirectory also below that fixed folder. Uses argv subprocess
invocations only; never shell=True. Returns structured source,
destination, and result fields; never exposes raw stdout, file contents,
or credential data.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

# Fixed cloud-download folder: slash plus U+4E91 U+4E0B U+8F7D.
# Kept as a Unicode literal in source per task spec.
FIXED_FOLDER: str = "/\u4e91\u4e0b\u8f7d"

# CLI binary name. Tests monkeypatch create_subprocess_exec instead.
CLI_BINARY: str = "115driver"

# Subprocess timeout in seconds. Conservative enough for CLI startup plus RPC.
CLI_TIMEOUT_SECONDS: float = 30.0

# Path length cap. Anything larger is rejected before invoking the CLI.
PATH_MAX_LENGTH: int = 4096

# Envelope code used by the CLI to signal "path not found" for stat.
_NOT_FOUND_CODE: int = 3


class CloudMoveError(Exception):
    """Sanitized cloud-move adapter error.

    The message is a stable, public-safe string. Raw CLI stdout/stderr and
    the submitted paths are never included in the message.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class StatInfo:
    """File info from stat: the path and whether it is a regular file."""

    file_id: str
    is_file: bool


@dataclass(frozen=True, slots=True)
class MoveResult:
    """Result of move_file: structured source, destination, and result."""

    source: str
    destination: str
    result: str


def _validate_tree_path(path: str) -> str:
    """Validate that path is strictly below the fixed folder.

    Rejects traversal (``..``), current-dir (``.``), empty segments, root
    moves (path equal to or above the fixed folder), malformed paths,
    control characters, command flags (segments starting with ``-``), and
    oversized input. Returns the path unchanged on success.

    Raises CloudMoveError with code CM-001 on rejection.
    """
    if not isinstance(path, str) or not path:
        raise CloudMoveError("CM-001", "Invalid path")
    if len(path) > PATH_MAX_LENGTH:
        raise CloudMoveError("CM-001", "Invalid path")
    if any(ord(ch) < 32 or ord(ch) == 127 or ch == "\\" for ch in path):
        raise CloudMoveError("CM-001", "Invalid path")

    prefix = FIXED_FOLDER + "/"
    if not path.startswith(prefix):
        raise CloudMoveError("CM-001", "Invalid path")
    remainder = path[len(prefix):]
    if not remainder:
        raise CloudMoveError("CM-001", "Invalid path")
    segments = remainder.split("/")
    if any(seg == "" for seg in segments):
        raise CloudMoveError("CM-001", "Invalid path")
    if any(seg in (".", "..") for seg in segments):
        raise CloudMoveError("CM-001", "Invalid path")
    if any(seg.startswith("-") for seg in segments):
        raise CloudMoveError("CM-001", "Invalid path")
    return path


def _basename(path: str) -> str:
    """Return the last path segment of a validated tree path."""
    return path.rsplit("/", 1)[-1]


def _build_stat_argv(path: str) -> list[str]:
    """Build the argv for the stat CLI call. Exposed for tests."""
    return [CLI_BINARY, "--json", "stat", "--", path]


def _build_mkdir_argv(path: str) -> list[str]:
    """Build the argv for the mkdir -p CLI call. Exposed for tests."""
    return [CLI_BINARY, "--json", "mkdir", "-p", "--", path]


def _build_mv_argv(source: str, destination: str) -> list[str]:
    """Build the argv for the mv CLI call. Exposed for tests."""
    return [CLI_BINARY, "--json", "mv", "--", source, destination]


async def _run_cli(argv: list[str], *, stat: bool = False) -> bytes:
    """Run the CLI subprocess and return stdout bytes.

    Uses asyncio.create_subprocess_exec with an argv list; never shell=True.
    Raises CloudMoveError on missing binary, timeout, or nonzero exit.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        raise CloudMoveError("CM-002", "CLI not available")
    except OSError:
        raise CloudMoveError("CM-002", "CLI not available")

    try:
        stdout, _stderr = await asyncio.wait_for(
            proc.communicate(), timeout=CLI_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        raise CloudMoveError("CM-003", "CLI timed out")

    if proc.returncode != 0 and not (stat and proc.returncode == _NOT_FOUND_CODE):
        raise CloudMoveError("CM-004", "CLI failed")
    return stdout


def _parse_envelope(payload: bytes) -> dict[str, Any]:
    """Parse the JSON envelope from CLI stdout.

    The envelope is a JSON object with a top-level ``data`` object. Raises
    CloudMoveError on malformed JSON or missing data.
    """
    try:
        envelope = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise CloudMoveError("CM-005", "CLI returned malformed output")
    if (
        not isinstance(envelope, dict)
        or envelope.get("success") is not True
        or envelope.get("code") != 0
        or not isinstance(envelope.get("data"), dict)
    ):
        raise CloudMoveError("CM-005", "CLI returned malformed output")
    return envelope["data"]


def _parse_stat_envelope(payload: bytes, expected_path: str) -> StatInfo | None:
    """Parse the stat envelope from CLI stdout.

    Returns StatInfo when the path exists, None when the CLI reports a
    not-found code. Raises CloudMoveError on any other shape.
    """
    try:
        envelope = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise CloudMoveError("CM-005", "CLI returned malformed output")
    if not isinstance(envelope, dict):
        raise CloudMoveError("CM-005", "CLI returned malformed output")

    if envelope.get("success") is True and envelope.get("code") == 0:
        data = envelope.get("data")
        if not isinstance(data, dict):
            raise CloudMoveError("CM-005", "CLI returned malformed output")
        name = data.get("name")
        file_id = data.get("file_id")
        is_dir = data.get("is_dir")
        if name != _basename(expected_path) or not isinstance(file_id, str) or not file_id or not isinstance(is_dir, bool):
            raise CloudMoveError("CM-005", "CLI returned malformed output")
        return StatInfo(file_id=file_id, is_file=not is_dir)

    if envelope.get("success") is False and envelope.get("code") == _NOT_FOUND_CODE:
        return None

    raise CloudMoveError("CM-005", "CLI returned malformed output")


def _parse_mkdir_result(data: dict[str, Any], expected: str) -> None:
    """Parse mkdir envelope data and verify the created path matches."""
    path = data.get("path")
    if not isinstance(path, str) or path != expected:
        raise CloudMoveError("CM-005", "CLI returned malformed output")


def _parse_mv_result(data: dict[str, Any], expected_src: str, expected_dir: str, source_file_id: str) -> None:
    """Parse mv envelope data and verify source and destination match."""
    source = data.get("source")
    destination = data.get("destination_dir")
    file_ids = data.get("file_ids")
    if not isinstance(source, str) or not isinstance(destination, str) or not isinstance(file_ids, list):
        raise CloudMoveError("CM-005", "CLI returned malformed output")
    if source != expected_src or destination != expected_dir or file_ids != [source_file_id]:
        raise CloudMoveError("CM-008", "Unexpected move result")


async def _stat(path: str) -> StatInfo | None:
    """Stat a path via the CLI.

    Returns StatInfo if the path exists, None if the CLI reports not-found.
    Raises CloudMoveError on CLI errors or malformed output.
    """
    argv = _build_stat_argv(path)
    stdout = await _run_cli(argv, stat=True)
    return _parse_stat_envelope(stdout, path)


async def _mkdir(path: str) -> None:
    """Create a directory via the CLI with mkdir -p semantics."""
    argv = _build_mkdir_argv(path)
    stdout = await _run_cli(argv)
    data = _parse_envelope(stdout)
    _parse_mkdir_result(data, path)


async def _mv(source: str, destination_dir: str, source_file_id: str) -> None:
    """Move a file via the CLI and verify the returned paths match."""
    argv = _build_mv_argv(source, destination_dir)
    stdout = await _run_cli(argv)
    data = _parse_envelope(stdout)
    _parse_mv_result(data, source, destination_dir, source_file_id)


async def move_file(source: str, destination_dir: str) -> MoveResult:
    """Move one existing file into a destination subdirectory.

    Both ``source`` and ``destination_dir`` must be strictly below the
    fixed cloud-download folder. The source must be an existing regular
    file; the destination_dir is created with mkdir -p if needed. A
    destination collision (the target file already exists) is rejected
    before mv. Fails closed on CLI errors or unexpected JSON.

    Returns a MoveResult with the sanitized source, the full destination
    file path, and the result string ``"moved"``.
    """
    sanitized_source = _validate_tree_path(source)
    sanitized_dest = _validate_tree_path(destination_dir)

    source_info = await _stat(sanitized_source)
    if source_info is None:
        raise CloudMoveError("CM-006", "Source not found")
    if not source_info.is_file:
        raise CloudMoveError("CM-006", "Source is not a file")

    await _mkdir(sanitized_dest)

    dest_file_path = sanitized_dest + "/" + _basename(sanitized_source)
    _validate_tree_path(dest_file_path)
    existing = await _stat(dest_file_path)
    if existing is not None:
        raise CloudMoveError("CM-007", "Destination already exists")

    await _mv(sanitized_source, sanitized_dest, source_info.file_id)

    return MoveResult(
        source=sanitized_source,
        destination=dest_file_path,
        result="moved",
    )
