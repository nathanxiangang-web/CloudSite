"""Cloud download driver: narrow async adapter for the 115driver v1.3.5 CLI.

Wraps the authenticated 115driver CLI for CloudSite cloud download. Uses an
argv subprocess invocation only; never passes shell=True. Returns structured
fields only; never exposes raw stdout, submitted URLs, or credential data.
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

# Fixed cloud-download destination folder: slash plus U+4E91 U+4E0B U+8F7D.
# Kept as a Unicode literal in source per task spec.
FIXED_FOLDER: str = "/\u4e91\u4e0b\u8f7d"

# CLI binary name. Tests monkeypatch create_subprocess_exec instead.
CLI_BINARY: str = "115driver"

# Subprocess timeout in seconds. Conservative enough for CLI startup plus RPC.
CLI_TIMEOUT_SECONDS: float = 30.0

# URL length cap. Anything larger is rejected before invoking the CLI.
URL_MAX_LENGTH: int = 2048

# Accepted URL schemes.
_ACCEPTED_SCHEMES: frozenset[str] = frozenset({"http", "https", "magnet", "ed2k"})

# Basic http/https form: require a non-empty host component after the scheme.
# magnet:?... form: require a non-empty query after the scheme marker.
_MAGNET_URL_RE = re.compile(r"^magnet:\?[^\s]+$")

# ed2k://|file|... form: require the leading segment marker and a first segment.
_ED2K_URL_RE = re.compile(r"^ed2k://\|[^\s|]+\|")

# BTIH extraction: 40-char hex or 32-char Base32, anywhere in the query string.
_BTIH_RE = re.compile(
    r"(?:^|[?&])xt=urn:btih:([A-Fa-f0-9]{40}|[A-Za-z2-7]{32})(?:&|$)",
    re.IGNORECASE,
)


class CloudDownloadError(Exception):
    """Sanitized cloud-download adapter error.

    The message is a stable, public-safe string. Raw CLI stdout/stderr and the
    submitted URL are never included in the message.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def normalize_magnet(url: str) -> str:
    """Reduce a magnet URI to its canonical BTIH-only form.

    Extracts the xt=urn:btih:<hash> parameter from anywhere in the query
    string, validates the hash (40-char hex or 32-char Base32), and returns
    a clean ``magnet:?xt=urn:btih:<hash>`` with all other parameters (dn,
    tr, xl, etc.) stripped.
    """
    match = _BTIH_RE.search(url)
    if not match:
        raise CloudDownloadError("CD-001", "Invalid magnet URL")

    btih = match.group(1)

    if len(btih) == 40:
        btih = btih.lower()

    return f"magnet:?xt=urn:btih:{btih}"


@dataclass(frozen=True, slots=True)
class AddOfflineResult:
    """Result of add_offline_task: only the structured fields callers need."""

    hashes: list[str]
    save_dir: str


@dataclass(frozen=True, slots=True)
class OfflineTask:
    """One item from list_offline_tasks."""

    hash: str
    name: str
    status: str
    percent: float
    size: int


def validate_url(url: str) -> str:
    """Validate a download URL for offline-task submission.

    Accepts http/https, magnet, and ed2k URLs. Rejects blank input, control
    characters, oversized input (length > URL_MAX_LENGTH), invalid schemes,
    and obviously malformed basic forms. Returns the URL unchanged on success.

    Raises CloudDownloadError with a stable code on rejection.
    """
    if not isinstance(url, str) or not url:
        raise CloudDownloadError("CD-001", "Invalid URL")
    if len(url) > URL_MAX_LENGTH:
        raise CloudDownloadError("CD-001", "Invalid URL")
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in url):
        raise CloudDownloadError("CD-001", "Invalid URL")

    scheme_sep = url.find(":")
    if scheme_sep <= 0:
        raise CloudDownloadError("CD-001", "Invalid URL")
    scheme = url[:scheme_sep].lower()
    if scheme not in _ACCEPTED_SCHEMES:
        raise CloudDownloadError("CD-001", "Invalid URL")

    if scheme in ("http", "https"):
        try:
            parsed = urlsplit(url)
            valid = (
                parsed.scheme.lower() == scheme
                and bool(parsed.hostname)
                and parsed.username is None
                and parsed.password is None
                and parsed.port != 0
            )
        except ValueError:
            valid = False
        if not valid:
            raise CloudDownloadError("CD-001", "Invalid URL")
    elif scheme == "magnet":
        if not _MAGNET_URL_RE.match(url):
            raise CloudDownloadError("CD-001", "Invalid URL")
        url = normalize_magnet(url)
    elif scheme == "ed2k":
        if not _ED2K_URL_RE.match(url):
            raise CloudDownloadError("CD-001", "Invalid URL")

    return url


def _build_add_argv(url: str) -> list[str]:
    """Build the argv for the offline add CLI call. Exposed for tests."""
    return [CLI_BINARY, "--json", "offline", "add", "-d", FIXED_FOLDER, "--", url]


def _build_list_argv() -> list[str]:
    """Build the argv for the offline list CLI call. Exposed for tests."""
    return [CLI_BINARY, "--json", "offline", "list"]


async def _run_cli(argv: list[str]) -> bytes:
    """Run the CLI subprocess and return stdout bytes.

    Uses asyncio.create_subprocess_exec with an argv list; never shell=True.
    Raises CloudDownloadError on missing binary, timeout, or nonzero exit.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        raise CloudDownloadError("CD-002", "CLI not available")
    except OSError:
        raise CloudDownloadError("CD-002", "CLI not available")

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
        raise CloudDownloadError("CD-003", "CLI timed out")

    if proc.returncode != 0:
        raise CloudDownloadError("CD-004", "CLI failed")
    return stdout


def _parse_envelope(payload: bytes) -> dict[str, Any]:
    """Parse the v1.3.5 JSON envelope from CLI stdout.

    The envelope is a JSON object with a top-level "data" object. Raises
    CloudDownloadError on malformed JSON or missing data.
    """
    try:
        envelope = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise CloudDownloadError("CD-005", "CLI returned malformed output")
    if (
        not isinstance(envelope, dict)
        or envelope.get("success") is not True
        or envelope.get("code") != 0
        or not isinstance(envelope.get("data"), dict)
    ):
        raise CloudDownloadError("CD-005", "CLI returned malformed output")
    return envelope["data"]


def _parse_add_result(data: dict[str, Any]) -> AddOfflineResult:
    """Parse the add offline task envelope data into AddOfflineResult."""
    raw_hashes = data.get("hashes")
    if (
        not isinstance(raw_hashes, list)
        or not raw_hashes
        or not all(isinstance(h, str) and h.strip() for h in raw_hashes)
    ):
        raise CloudDownloadError("CD-005", "CLI returned malformed output")
    save_dir = data.get("save_dir")
    if not isinstance(save_dir, str):
        raise CloudDownloadError("CD-005", "CLI returned malformed output")
    if save_dir != FIXED_FOLDER:
        raise CloudDownloadError("CD-006", "Unexpected destination folder")
    return AddOfflineResult(hashes=list(raw_hashes), save_dir=save_dir)


def _parse_list_result(data: dict[str, Any]) -> list[OfflineTask]:
    """Parse the list offline tasks envelope data into a list of OfflineTask."""
    raw_tasks = data.get("tasks")
    if not isinstance(raw_tasks, list):
        raise CloudDownloadError("CD-005", "CLI returned malformed output")
    tasks: list[OfflineTask] = []
    for item in raw_tasks:
        if not isinstance(item, dict):
            raise CloudDownloadError("CD-005", "CLI returned malformed output")
        hash_ = item.get("hash")
        name = item.get("name")
        status = item.get("status")
        percent = item.get("percent")
        size = item.get("size")
        if not isinstance(hash_, str) or not isinstance(name, str) or not isinstance(status, str):
            raise CloudDownloadError("CD-005", "CLI returned malformed output")
        if not isinstance(percent, (int, float)) or isinstance(percent, bool):
            raise CloudDownloadError("CD-005", "CLI returned malformed output")
        if not isinstance(size, int) or isinstance(size, bool):
            raise CloudDownloadError("CD-005", "CLI returned malformed output")
        tasks.append(
            OfflineTask(
                hash=hash_,
                name=name,
                status=status,
                percent=float(percent),
                size=size,
            )
        )
    return tasks


async def add_offline_task(url: str) -> AddOfflineResult:
    """Submit a URL as an offline download task to the fixed cloud folder.

    Validates the URL, invokes
    ``115driver --json offline add -d <fixed-folder> -- URL``
    via an argv subprocess (never shell), parses the v1.3.5 envelope, and
    returns only the hashes and save_dir. Never logs the URL or raw CLI errors.
    """
    sanitized = validate_url(url)
    argv = _build_add_argv(sanitized)
    stdout = await _run_cli(argv)
    data = _parse_envelope(stdout)
    return _parse_add_result(data)


async def list_offline_tasks() -> list[OfflineTask]:
    """List current offline tasks from the CLI.

    Invokes ``115driver --json offline list`` via an argv subprocess (never
    shell), parses the v1.3.5 envelope, and returns only the structured task
    fields: hash, name, status, percent, size.
    """
    argv = _build_list_argv()
    stdout = await _run_cli(argv)
    data = _parse_envelope(stdout)
    return _parse_list_result(data)
