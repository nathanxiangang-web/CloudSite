"""Focused mocked unit tests for cloud_move_driver.

Covers: success path, invalid paths (traversal, empty segments, root
moves, malformed paths, command flags, out-of-tree destinations),
destination collision, source not found, source not a file, malformed
JSON, nonzero exit, timeout, missing CLI, unexpected mv result, and
sanitized errors. No live account access; the CLI subprocess factory is
mocked in every test.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from cloudsite.services import cloud_move_driver as drv


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
    return json.dumps({"success": True, "code": 0, "data": data}).encode("utf-8")


def _not_found_envelope() -> bytes:
    return json.dumps({"success": False, "code": 404, "data": None}).encode("utf-8")


def _stat_envelope(path: str, is_file: bool) -> bytes:
    return _envelope({"path": path, "is_file": is_file})


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


def _src() -> str:
    return drv.FIXED_FOLDER + "/inbox/file.zip"


def _dest_dir() -> str:
    return drv.FIXED_FOLDER + "/archive"


def _dest_file() -> str:
    return drv.FIXED_FOLDER + "/archive/file.zip"


# --- path validation tests ------------------------------------------------

def test_validate_tree_path_accepts_file_below_fixed_folder():
    assert drv._validate_tree_path(drv.FIXED_FOLDER + "/a/b.zip") == drv.FIXED_FOLDER + "/a/b.zip"


def test_validate_tree_path_accepts_single_segment():
    assert drv._validate_tree_path(drv.FIXED_FOLDER + "/file.zip") == drv.FIXED_FOLDER + "/file.zip"


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "not-a-path",
        "/wrong/file.zip",
        drv.FIXED_FOLDER,
        drv.FIXED_FOLDER + "/",
        drv.FIXED_FOLDER + "//file.zip",
        drv.FIXED_FOLDER + "/a//b.zip",
        drv.FIXED_FOLDER + "/../file.zip",
        drv.FIXED_FOLDER + "/a/../../file.zip",
        drv.FIXED_FOLDER + "/./file.zip",
        drv.FIXED_FOLDER + "/a/./b.zip",
        drv.FIXED_FOLDER + "/-flag",
        drv.FIXED_FOLDER + "/a/-rm",
        drv.FIXED_FOLDER + "/..",
    ],
)
def test_validate_tree_path_rejects_invalid(bad):
    with pytest.raises(drv.CloudMoveError) as exc:
        drv._validate_tree_path(bad)
    assert exc.value.code == "CM-001"


def test_validate_tree_path_rejects_non_string():
    with pytest.raises(drv.CloudMoveError):
        drv._validate_tree_path(None)  # type: ignore[arg-type]


def test_validate_tree_path_rejects_control_chars():
    with pytest.raises(drv.CloudMoveError) as exc:
        drv._validate_tree_path(drv.FIXED_FOLDER + "/a\nb.zip")
    assert exc.value.code == "CM-001"


def test_validate_tree_path_rejects_oversized():
    path = drv.FIXED_FOLDER + "/" + "a" * drv.PATH_MAX_LENGTH
    with pytest.raises(drv.CloudMoveError) as exc:
        drv._validate_tree_path(path)
    assert exc.value.code == "CM-001"


# --- argv contract tests --------------------------------------------------

def test_stat_argv_contract():
    argv = drv._build_stat_argv(drv.FIXED_FOLDER + "/file.zip")
    assert argv == [drv.CLI_BINARY, "--json", "stat", "--", drv.FIXED_FOLDER + "/file.zip"]


def test_mkdir_argv_contract():
    argv = drv._build_mkdir_argv(drv.FIXED_FOLDER + "/sub")
    assert argv == [drv.CLI_BINARY, "--json", "mkdir", "-p", "--", drv.FIXED_FOLDER + "/sub"]


def test_mv_argv_contract():
    src = drv.FIXED_FOLDER + "/a.zip"
    dst = drv.FIXED_FOLDER + "/sub/a.zip"
    argv = drv._build_mv_argv(src, dst)
    assert argv == [drv.CLI_BINARY, "--json", "mv", "--", src, dst]


def test_argv_is_plain_string_list():
    argv = drv._build_mv_argv(drv.FIXED_FOLDER + "/a", drv.FIXED_FOLDER + "/b/a")
    assert isinstance(argv, list)
    assert all(isinstance(a, str) for a in argv)


def test_fixed_folder_is_unicode_cloud_download():
    assert drv.FIXED_FOLDER == "/\u4e91\u4e0b\u8f7d"


# --- move_file success ----------------------------------------------------

async def test_move_file_success(fake_subprocess):
    calls, queue = fake_subprocess
    queue.append(_make_proc(stdout=_stat_envelope(_src(), is_file=True)))
    queue.append(_make_proc(stdout=_envelope({"path": _dest_dir()})))
    queue.append(_make_proc(stdout=_not_found_envelope()))
    queue.append(_make_proc(stdout=_envelope({"source": _src(), "destination": _dest_file()})))

    result = await drv.move_file(_src(), _dest_dir())

    assert result.source == _src()
    assert result.destination == _dest_file()
    assert result.result == "moved"
    assert calls[0] == drv._build_stat_argv(_src())
    assert calls[1] == drv._build_mkdir_argv(_dest_dir())
    assert calls[2] == drv._build_stat_argv(_dest_file())
    assert calls[3] == drv._build_mv_argv(_src(), _dest_file())


async def test_move_file_rejects_invalid_source_before_cli(fake_subprocess):
    calls, queue = fake_subprocess
    with pytest.raises(drv.CloudMoveError) as exc:
        await drv.move_file(drv.FIXED_FOLDER + "/../escape.zip", _dest_dir())
    assert exc.value.code == "CM-001"
    assert calls == []


async def test_move_file_rejects_invalid_destination_before_cli(fake_subprocess):
    calls, queue = fake_subprocess
    with pytest.raises(drv.CloudMoveError) as exc:
        await drv.move_file(_src(), "/wrong/dir")
    assert exc.value.code == "CM-001"
    assert calls == []


async def test_move_file_rejects_root_source(fake_subprocess):
    calls, _ = fake_subprocess
    with pytest.raises(drv.CloudMoveError) as exc:
        await drv.move_file(drv.FIXED_FOLDER, _dest_dir())
    assert exc.value.code == "CM-001"
    assert calls == []


async def test_move_file_rejects_root_destination(fake_subprocess):
    calls, _ = fake_subprocess
    with pytest.raises(drv.CloudMoveError) as exc:
        await drv.move_file(_src(), drv.FIXED_FOLDER)
    assert exc.value.code == "CM-001"
    assert calls == []


# --- source not found / not a file ----------------------------------------

async def test_move_file_source_not_found(fake_subprocess):
    calls, queue = fake_subprocess
    queue.append(_make_proc(stdout=_not_found_envelope()))
    with pytest.raises(drv.CloudMoveError) as exc:
        await drv.move_file(_src(), _dest_dir())
    assert exc.value.code == "CM-006"
    assert len(calls) == 1


async def test_move_file_source_is_directory(fake_subprocess):
    _, queue = fake_subprocess
    queue.append(_make_proc(stdout=_stat_envelope(_src(), is_file=False)))
    with pytest.raises(drv.CloudMoveError) as exc:
        await drv.move_file(_src(), _dest_dir())
    assert exc.value.code == "CM-006"


# --- destination collision ------------------------------------------------

async def test_move_file_destination_collision(fake_subprocess):
    calls, queue = fake_subprocess
    queue.append(_make_proc(stdout=_stat_envelope(_src(), is_file=True)))
    queue.append(_make_proc(stdout=_envelope({"path": _dest_dir()})))
    queue.append(_make_proc(stdout=_stat_envelope(_dest_file(), is_file=True)))
    with pytest.raises(drv.CloudMoveError) as exc:
        await drv.move_file(_src(), _dest_dir())
    assert exc.value.code == "CM-007"
    assert len(calls) == 3


async def test_move_file_collision_check_uses_stat_on_dest_file(fake_subprocess):
    calls, queue = fake_subprocess
    queue.append(_make_proc(stdout=_stat_envelope(_src(), is_file=True)))
    queue.append(_make_proc(stdout=_envelope({"path": _dest_dir()})))
    queue.append(_make_proc(stdout=_stat_envelope(_dest_file(), is_file=False)))
    with pytest.raises(drv.CloudMoveError) as exc:
        await drv.move_file(_src(), _dest_dir())
    assert exc.value.code == "CM-007"
    assert calls[2] == drv._build_stat_argv(_dest_file())


# --- malformed JSON -------------------------------------------------------

async def test_move_file_stat_malformed_json(fake_subprocess):
    _, queue = fake_subprocess
    queue.append(_make_proc(stdout=b"not json"))
    with pytest.raises(drv.CloudMoveError) as exc:
        await drv.move_file(_src(), _dest_dir())
    assert exc.value.code == "CM-005"


async def test_move_file_mkdir_malformed_json(fake_subprocess):
    _, queue = fake_subprocess
    queue.append(_make_proc(stdout=_stat_envelope(_src(), is_file=True)))
    queue.append(_make_proc(stdout=b"{broken"))
    with pytest.raises(drv.CloudMoveError) as exc:
        await drv.move_file(_src(), _dest_dir())
    assert exc.value.code == "CM-005"


async def test_move_file_collision_stat_malformed_json(fake_subprocess):
    _, queue = fake_subprocess
    queue.append(_make_proc(stdout=_stat_envelope(_src(), is_file=True)))
    queue.append(_make_proc(stdout=_envelope({"path": _dest_dir()})))
    queue.append(_make_proc(stdout=b"not json"))
    with pytest.raises(drv.CloudMoveError) as exc:
        await drv.move_file(_src(), _dest_dir())
    assert exc.value.code == "CM-005"


async def test_move_file_mv_malformed_json(fake_subprocess):
    _, queue = fake_subprocess
    queue.append(_make_proc(stdout=_stat_envelope(_src(), is_file=True)))
    queue.append(_make_proc(stdout=_envelope({"path": _dest_dir()})))
    queue.append(_make_proc(stdout=_not_found_envelope()))
    queue.append(_make_proc(stdout=b"not json"))
    with pytest.raises(drv.CloudMoveError) as exc:
        await drv.move_file(_src(), _dest_dir())
    assert exc.value.code == "CM-005"


async def test_move_file_stat_missing_data_key(fake_subprocess):
    _, queue = fake_subprocess
    queue.append(_make_proc(stdout=json.dumps({"error": "oops"}).encode("utf-8")))
    with pytest.raises(drv.CloudMoveError) as exc:
        await drv.move_file(_src(), _dest_dir())
    assert exc.value.code == "CM-005"


async def test_move_file_stat_bad_is_file_type(fake_subprocess):
    _, queue = fake_subprocess
    queue.append(_make_proc(stdout=_envelope({"path": _src(), "is_file": "yes"})))
    with pytest.raises(drv.CloudMoveError) as exc:
        await drv.move_file(_src(), _dest_dir())
    assert exc.value.code == "CM-005"


async def test_move_file_mkdir_path_mismatch(fake_subprocess):
    _, queue = fake_subprocess
    queue.append(_make_proc(stdout=_stat_envelope(_src(), is_file=True)))
    queue.append(_make_proc(stdout=_envelope({"path": "/wrong"})))
    with pytest.raises(drv.CloudMoveError) as exc:
        await drv.move_file(_src(), _dest_dir())
    assert exc.value.code == "CM-005"


# --- unexpected mv result -------------------------------------------------

async def test_move_file_mv_destination_mismatch(fake_subprocess):
    _, queue = fake_subprocess
    queue.append(_make_proc(stdout=_stat_envelope(_src(), is_file=True)))
    queue.append(_make_proc(stdout=_envelope({"path": _dest_dir()})))
    queue.append(_make_proc(stdout=_not_found_envelope()))
    queue.append(_make_proc(stdout=_envelope({"source": _src(), "destination": "/wrong"})))
    with pytest.raises(drv.CloudMoveError) as exc:
        await drv.move_file(_src(), _dest_dir())
    assert exc.value.code == "CM-008"


async def test_move_file_mv_source_mismatch(fake_subprocess):
    _, queue = fake_subprocess
    queue.append(_make_proc(stdout=_stat_envelope(_src(), is_file=True)))
    queue.append(_make_proc(stdout=_envelope({"path": _dest_dir()})))
    queue.append(_make_proc(stdout=_not_found_envelope()))
    queue.append(_make_proc(stdout=_envelope({"source": "/wrong", "destination": _dest_file()})))
    with pytest.raises(drv.CloudMoveError) as exc:
        await drv.move_file(_src(), _dest_dir())
    assert exc.value.code == "CM-008"


# --- nonzero exit ---------------------------------------------------------

async def test_move_file_nonzero_exit_on_stat(fake_subprocess):
    _, queue = fake_subprocess
    queue.append(_make_proc(stdout=b"", returncode=2))
    with pytest.raises(drv.CloudMoveError) as exc:
        await drv.move_file(_src(), _dest_dir())
    assert exc.value.code == "CM-004"


async def test_move_file_nonzero_exit_on_mkdir(fake_subprocess):
    _, queue = fake_subprocess
    queue.append(_make_proc(stdout=_stat_envelope(_src(), is_file=True)))
    queue.append(_make_proc(stdout=b"", returncode=1))
    with pytest.raises(drv.CloudMoveError) as exc:
        await drv.move_file(_src(), _dest_dir())
    assert exc.value.code == "CM-004"


async def test_move_file_nonzero_exit_on_mv(fake_subprocess):
    _, queue = fake_subprocess
    queue.append(_make_proc(stdout=_stat_envelope(_src(), is_file=True)))
    queue.append(_make_proc(stdout=_envelope({"path": _dest_dir()})))
    queue.append(_make_proc(stdout=_not_found_envelope()))
    queue.append(_make_proc(stdout=b"", returncode=1))
    with pytest.raises(drv.CloudMoveError) as exc:
        await drv.move_file(_src(), _dest_dir())
    assert exc.value.code == "CM-004"


# --- timeout ---------------------------------------------------------------

async def test_move_file_timeout(monkeypatch):
    async def _hang_exec(*argv, **kwargs):
        class _HangProc:
            returncode = None

            async def communicate(self):
                await asyncio.sleep(3600)
                return b"", b""

            def kill(self):
                pass

            async def wait(self):
                return -9

        return _HangProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _hang_exec)
    monkeypatch.setattr(drv, "CLI_TIMEOUT_SECONDS", 0.01)
    with pytest.raises(drv.CloudMoveError) as exc:
        await drv.move_file(_src(), _dest_dir())
    assert exc.value.code == "CM-003"


# --- missing CLI ----------------------------------------------------------

async def test_move_file_missing_cli(monkeypatch):
    async def _missing_exec(*argv, **kwargs):
        raise FileNotFoundError("115driver")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _missing_exec)
    with pytest.raises(drv.CloudMoveError) as exc:
        await drv.move_file(_src(), _dest_dir())
    assert exc.value.code == "CM-002"


async def test_move_file_oserror_treated_as_missing_cli(monkeypatch):
    async def _bad_exec(*argv, **kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _bad_exec)
    with pytest.raises(drv.CloudMoveError) as exc:
        await drv.move_file(_src(), _dest_dir())
    assert exc.value.code == "CM-002"


# --- sanitized errors never leak paths or raw output -----------------------

async def test_error_messages_do_not_leak_paths_or_stdout(fake_subprocess):
    secret_path = drv.FIXED_FOLDER + "/secret/file.zip"
    _, queue = fake_subprocess
    queue.append(_make_proc(stdout=b"RAW CLI DEBUG WITH PATH " + secret_path.encode()))
    with pytest.raises(drv.CloudMoveError) as exc:
        await drv.move_file(secret_path, _dest_dir())
    assert secret_path not in exc.value.message
    assert "RAW CLI DEBUG" not in exc.value.message


async def test_nonzero_exit_error_does_not_leak_stderr(fake_subprocess):
    _, queue = fake_subprocess
    queue.append(_make_proc(stdout=b"", stderr=b"credential leak in stderr", returncode=1))
    with pytest.raises(drv.CloudMoveError) as exc:
        await drv.move_file(_src(), _dest_dir())
    assert "credential leak" not in exc.value.message


async def test_collision_error_does_not_leak_dest_path(fake_subprocess):
    secret_dest = drv.FIXED_FOLDER + "/vault"
    _, queue = fake_subprocess
    queue.append(_make_proc(stdout=_stat_envelope(_src(), is_file=True)))
    queue.append(_make_proc(stdout=_envelope({"path": secret_dest})))
    queue.append(_make_proc(stdout=_stat_envelope(secret_dest + "/file.zip", is_file=True)))
    with pytest.raises(drv.CloudMoveError) as exc:
        await drv.move_file(_src(), secret_dest)
    assert exc.value.code == "CM-007"
    assert secret_dest not in exc.value.message
