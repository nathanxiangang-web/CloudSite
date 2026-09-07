"""8.5 单元测试：validate_paths_under_roots 路径校验"""
import pytest

from cloudsite.sync.path_sync import validate_paths_under_roots, MAX_PATHS


def _make_root(path: str, enabled: bool = True):
    from types import SimpleNamespace
    return SimpleNamespace(alist_path=path, enabled=enabled)


def test_valid_path_under_root_accepted():
    roots = [_make_root("/软件")]
    accepted, rejected = validate_paths_under_roots(["/软件/sub"], roots)
    assert accepted == ["/软件/sub"]
    assert rejected == []


def test_root_itself_accepted():
    roots = [_make_root("/软件")]
    accepted, rejected = validate_paths_under_roots(["/软件"], roots)
    assert accepted == ["/软件"]
    assert rejected == []


def test_path_not_under_any_root_rejected():
    roots = [_make_root("/软件")]
    accepted, rejected = validate_paths_under_roots(["/图片/foo"], roots)
    assert accepted == []
    assert len(rejected) == 1
    assert rejected[0]["path"] == "/图片/foo"
    assert "不在" in rejected[0]["reason"]


def test_mixed_paths_partial_accept():
    roots = [_make_root("/软件"), _make_root("/图片")]
    accepted, rejected = validate_paths_under_roots(["/软件/valid", "/other/invalid"], roots)
    assert accepted == ["/软件/valid"]
    assert len(rejected) == 1


def test_all_invalid_returns_empty_accepted():
    roots = [_make_root("/软件")]
    accepted, rejected = validate_paths_under_roots(["/other1", "/other2"], roots)
    assert accepted == []
    assert len(rejected) == 2


def test_disabled_root_ignored():
    roots = [_make_root("/软件", enabled=False), _make_root("/图片", enabled=True)]
    accepted, rejected = validate_paths_under_roots(["/软件/sub", "/图片/sub"], roots)
    assert "/软件/sub" not in accepted
    assert "/图片/sub" in accepted


def test_exceeds_max_paths_rejected():
    roots = [_make_root("/软件")]
    paths = [f"/软件/{i}" for i in range(MAX_PATHS + 1)]
    accepted, rejected = validate_paths_under_roots(paths, roots)
    assert accepted == []
    assert len(rejected) == 1
    assert "超过" in rejected[0]["reason"]


def test_path_normalization_strips_trailing_slash():
    roots = [_make_root("/软件/")]
    accepted, rejected = validate_paths_under_roots(["/软件/sub"], roots)
    assert accepted == ["/软件/sub"]


def test_path_traversal_segment_rejected():
    roots = [_make_root("/软件")]
    accepted, rejected = validate_paths_under_roots(["/软件/../图片"], roots)
    assert accepted == []
    assert len(rejected) == 1
    assert ".." in rejected[0]["reason"]