"""Focused mocked unit tests for cloud_download_driver.

Covers: success path, malformed JSON, nonzero exit, timeout, missing CLI,
URL validation, and argv/path contract. No live account access; the CLI
subprocess factory is mocked in every test.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from cloudsite.services import cloud_download_driver as drv


def _make_proc(stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0):
    """Build a fake asyncio subprocess with a controllable communicate()."""

    class _FakeProc:
        def __init__(self):
            self.returncode = returncode
            self._stdout = stdout
            self._stderr = stderr
            self.killed = False

        async def communicate(self):
            return self._stdout, self._stderr

        def kill(self):
            self.killed = True

    return _FakeProc()


def _envelope(data: dict) -> bytes:
    return json.dumps({"data": data}).encode("utf-8")


@pytest.fixture
def fake_subprocess(monkeypatch):
    """Capture create_subprocess_exec calls and return a queued fake proc."""
    calls: list[list[str]] = []
    queue: list = []

    async def _fake_exec(*argv, **kwargs):
        calls.append(list(argv))
        if not queue:
            raise AssertionError("no queued fake proc for create_subprocess_exec")
        proc = queue.pop(0)
        if isinstance(proc, Exception):
            raise proc
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    return calls, queue


# --- URL validation tests -------------------------------------------------

def test_validate_url_accepts_http():
    assert drv.validate_url("http://example.com/file.zip") == "http://example.com/file.zip"


def test_validate_url_accepts_https():
    assert drv.validate_url("https://example.com/file.zip") == "https://example.com/file.zip"


def test_validate_url_accepts_magnet():
    url = "magnet:?xt=urn:btih:abcdef1234567890"
    assert drv.validate_url(url) == url


def test_validate_url_accepts_ed2k():
    url = "ed2k://|file|name.zip|1024|abcdef1234567890|/"
    assert drv.validate_url(url) == url


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "ftp://example.com/file",
        "javascript:alert(1)",
        "http://",
        "https:///",
        "magnet:",
        "ed2k://|",
        "not a url",
        ":noscheme",
    ],
)
def test_validate_url_rejects_invalid(bad):
    with pytest.raises(drv.CloudDownloadError) as exc:
        drv.validate_url(bad)
    assert exc.value.code == "CD-001"


def test_validate_url_rejects_control_chars():
    with pytest.raises(drv.CloudDownloadError) as exc:
        drv.validate_url("http://example.com\nfile")
    assert exc.value.code == "CD-001"


def test_validate_url_rejects_tab():
    with pytest.raises(drv.CloudDownloadError):
        drv.validate_url("http://example.com\tfile")


def test_validate_url_rejects_oversized():
    url = "http://example.com/" + "a" * drv.URL_MAX_LENGTH
    with pytest.raises(drv.CloudDownloadError) as exc:
        drv.validate_url(url)
    assert exc.value.code == "CD-001"


def test_validate_url_rejects_non_string():
    with pytest.raises(drv.CloudDownloadError):
        drv.validate_url(None)  # type: ignore[arg-type]


def test_validate_url_accepts_max_length_boundary():
    url = "http://e.co/" + "a" * (drv.URL_MAX_LENGTH - len("http://e.co/"))
    assert len(url) == drv.URL_MAX_LENGTH
    assert drv.validate_url(url) == url


# --- argv / path contract tests -------------------------------------------

def test_add_argv_uses_fixed_folder_and_url():
    argv = drv._build_add_argv("http://example.com/file.zip")
    assert argv[0] == drv.CLI_BINARY
    assert "--json" in argv
    assert "offline" in argv and "add" in argv
    assert "-d" in argv
    d_index = argv.index("-d")
    assert argv[d_index + 1] == drv.FIXED_FOLDER
    assert "--" in argv
    assert argv[-1] == "http://example.com/file.zip"


def test_add_argv_fixed_folder_is_unicode_cloud_download():
    assert drv.FIXED_FOLDER == "/\u4e91\u4e0b\u8f7d"


def test_list_argv_contract():
    argv = drv._build_list_argv()
    assert argv == [drv.CLI_BINARY, "--json", "offline", "list"]


def test_add_argv_is_plain_string_list():
    argv = drv._build_add_argv("http://example.com/file.zip")
    assert isinstance(argv, list)
    assert all(isinstance(a, str) for a in argv)


# --- add_offline_task success ---------------------------------------------

async def test_add_offline_task_success(fake_subprocess):
    calls, queue = fake_subprocess
    queue.append(
        _make_proc(stdout=_envelope({"hashes": ["h1", "h2"], "save_dir": drv.FIXED_FOLDER}))
    )
    result = await drv.add_offline_task("http://example.com/file.zip")
    assert result.hashes == ["h1", "h2"]
    assert result.save_dir == drv.FIXED_FOLDER
    assert calls[0] == drv._build_add_argv("http://example.com/file.zip")


async def test_add_offline_task_rejects_invalid_url_before_cli(fake_subprocess):
    calls, queue = fake_subprocess
    with pytest.raises(drv.CloudDownloadError) as exc:
        await drv.add_offline_task("")
    assert exc.value.code == "CD-001"
    assert calls == []


async def test_add_offline_task_save_dir_mismatch(fake_subprocess):
    _, queue = fake_subprocess
    queue.append(_make_proc(stdout=_envelope({"hashes": ["h1"], "save_dir": "/wrong"})))
    with pytest.raises(drv.CloudDownloadError) as exc:
        await drv.add_offline_task("http://example.com/file.zip")
    assert exc.value.code == "CD-006"


async def test_add_offline_task_magnet_success(fake_subprocess):
    calls, queue = fake_subprocess
    magnet = "magnet:?xt=urn:btih:abcdef"
    queue.append(_make_proc(stdout=_envelope({"hashes": ["h1"], "save_dir": drv.FIXED_FOLDER})))
    result = await drv.add_offline_task(magnet)
    assert result.hashes == ["h1"]
    assert calls[0][-1] == magnet


# --- list_offline_tasks success -------------------------------------------

async def test_list_offline_tasks_success(fake_subprocess):
    calls, queue = fake_subprocess
    queue.append(
        _make_proc(
            stdout=_envelope(
                {
                    "tasks": [
                        {"hash": "h1", "name": "a.zip", "status": "running", "percent": 50.0, "size": 1024},
                        {"hash": "h2", "name": "b.zip", "status": "done", "percent": 100, "size": 2048},
                    ]
                }
            )
        )
    )
    tasks = await drv.list_offline_tasks()
    assert len(tasks) == 2
    assert tasks[0].hash == "h1"
    assert tasks[0].name == "a.zip"
    assert tasks[0].status == "running"
    assert tasks[0].percent == 50.0
    assert tasks[0].size == 1024
    assert tasks[1].hash == "h2"
    assert tasks[1].percent == 100.0
    assert calls[0] == drv._build_list_argv()


async def test_list_offline_tasks_empty(fake_subprocess):
    _, queue = fake_subprocess
    queue.append(_make_proc(stdout=_envelope({"tasks": []})))
    tasks = await drv.list_offline_tasks()
    assert tasks == []


# --- malformed JSON -------------------------------------------------------

async def test_add_offline_task_malformed_json(fake_subprocess):
    _, queue = fake_subprocess
    queue.append(_make_proc(stdout=b"not json at all"))
    with pytest.raises(drv.CloudDownloadError) as exc:
        await drv.add_offline_task("http://example.com/file.zip")
    assert exc.value.code == "CD-005"


async def test_list_offline_tasks_malformed_json(fake_subprocess):
    _, queue = fake_subprocess
    queue.append(_make_proc(stdout=b"{broken"))
    with pytest.raises(drv.CloudDownloadError) as exc:
        await drv.list_offline_tasks()
    assert exc.value.code == "CD-005"


async def test_add_offline_task_missing_data_key(fake_subprocess):
    _, queue = fake_subprocess
    queue.append(_make_proc(stdout=json.dumps({"error": "oops"}).encode("utf-8")))
    with pytest.raises(drv.CloudDownloadError) as exc:
        await drv.add_offline_task("http://example.com/file.zip")
    assert exc.value.code == "CD-005"


async def test_add_offline_task_hashes_not_list(fake_subprocess):
    _, queue = fake_subprocess
    queue.append(_make_proc(stdout=_envelope({"hashes": "h1", "save_dir": drv.FIXED_FOLDER})))
    with pytest.raises(drv.CloudDownloadError) as exc:
        await drv.add_offline_task("http://example.com/file.zip")
    assert exc.value.code == "CD-005"


async def test_list_offline_tasks_item_missing_field(fake_subprocess):
    _, queue = fake_subprocess
    queue.append(
        _make_proc(
            stdout=_envelope({"tasks": [{"hash": "h1", "name": "a", "status": "running"}]})
        )
    )
    with pytest.raises(drv.CloudDownloadError) as exc:
        await drv.list_offline_tasks()
    assert exc.value.code == "CD-005"


# --- nonzero exit ---------------------------------------------------------

async def test_add_offline_task_nonzero_exit(fake_subprocess):
    _, queue = fake_subprocess
    queue.append(_make_proc(stdout=b"", returncode=2))
    with pytest.raises(drv.CloudDownloadError) as exc:
        await drv.add_offline_task("http://example.com/file.zip")
    assert exc.value.code == "CD-004"


async def test_list_offline_tasks_nonzero_exit(fake_subprocess):
    _, queue = fake_subprocess
    queue.append(_make_proc(stdout=b"", returncode=1))
    with pytest.raises(drv.CloudDownloadError) as exc:
        await drv.list_offline_tasks()
    assert exc.value.code == "CD-004"


# --- timeout --------------------------------------------------------------

async def test_add_offline_task_timeout(monkeypatch):
    async def _hang_exec(*argv, **kwargs):
        class _HangProc:
            returncode = None

            async def communicate(self):
                await asyncio.sleep(3600)
                return b"", b""

            def kill(self):
                pass

        return _HangProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _hang_exec)
    monkeypatch.setattr(drv, "CLI_TIMEOUT_SECONDS", 0.01)
    with pytest.raises(drv.CloudDownloadError) as exc:
        await drv.add_offline_task("http://example.com/file.zip")
    assert exc.value.code == "CD-003"


async def test_list_offline_tasks_timeout(monkeypatch):
    async def _hang_exec(*argv, **kwargs):
        class _HangProc:
            returncode = None

            async def communicate(self):
                await asyncio.sleep(3600)
                return b"", b""

            def kill(self):
                pass

        return _HangProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _hang_exec)
    monkeypatch.setattr(drv, "CLI_TIMEOUT_SECONDS", 0.01)
    with pytest.raises(drv.CloudDownloadError) as exc:
        await drv.list_offline_tasks()
    assert exc.value.code == "CD-003"


# --- missing CLI ----------------------------------------------------------

async def test_add_offline_task_missing_cli(monkeypatch):
    async def _missing_exec(*argv, **kwargs):
        raise FileNotFoundError("115driver")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _missing_exec)
    with pytest.raises(drv.CloudDownloadError) as exc:
        await drv.add_offline_task("http://example.com/file.zip")
    assert exc.value.code == "CD-002"


async def test_list_offline_tasks_missing_cli(monkeypatch):
    async def _missing_exec(*argv, **kwargs):
        raise FileNotFoundError("115driver")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _missing_exec)
    with pytest.raises(drv.CloudDownloadError) as exc:
        await drv.list_offline_tasks()
    assert exc.value.code == "CD-002"


async def test_add_offline_task_oserror_treated_as_missing_cli(monkeypatch):
    async def _bad_exec(*argv, **kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _bad_exec)
    with pytest.raises(drv.CloudDownloadError) as exc:
        await drv.add_offline_task("http://example.com/file.zip")
    assert exc.value.code == "CD-002"


# --- sanitized errors never leak URL or raw output ------------------------

async def test_error_messages_do_not_leak_url_or_stdout(fake_subprocess):
    url = "http://example.com/secret-path/file.zip"
    _, queue = fake_subprocess
    queue.append(_make_proc(stdout=b"RAW CLI DEBUG WITH URL " + url.encode()))
    with pytest.raises(drv.CloudDownloadError) as exc:
        await drv.add_offline_task(url)
    assert url not in exc.value.message
    assert "RAW CLI DEBUG" not in exc.value.message


async def test_nonzero_exit_error_does_not_leak_stderr(fake_subprocess):
    _, queue = fake_subprocess
    queue.append(_make_proc(stdout=b"", stderr=b"credential leak in stderr", returncode=1))
    with pytest.raises(drv.CloudDownloadError) as exc:
        await drv.add_offline_task("http://example.com/file.zip")
    assert "credential leak" not in exc.value.message
