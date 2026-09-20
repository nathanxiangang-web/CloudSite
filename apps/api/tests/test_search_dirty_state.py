"""R7 PR03: Search Dirty Recovery state tests (V2 doc section 39)."""

from __future__ import annotations

from datetime import datetime, timezone

from cloudsite.modules.indexing.domain.search_dirty_state import SearchDirtyState

_NOW = datetime(2026, 9, 21, 1, 0, 0, tzinfo=timezone.utc)


def test_default_state_is_clean():
    s = SearchDirtyState(root_mapping_id=1)
    assert s.search_dirty is False
    assert s.needs_replay is False
    assert s.has_error is False


def test_mark_dirty():
    s = SearchDirtyState(root_mapping_id=1)
    s.mark_dirty("fts_error", "FTS write failed", now=_NOW)
    assert s.search_dirty is True
    assert s.needs_replay is True
    assert s.has_error is True
    assert s.last_error_code == "fts_error"
    assert s.last_error_message == "FTS write failed"
    assert s.last_failure_at == _NOW


def test_mark_clean():
    s = SearchDirtyState(root_mapping_id=1)
    s.mark_dirty("err", "fail", now=_NOW)
    s.mark_clean(now=_NOW)
    assert s.search_dirty is False
    assert s.needs_replay is False
    assert s.has_error is False
    assert s.last_error_code is None
    assert s.last_error_message is None
    assert s.last_success_at == _NOW


def test_increment_replay_attempt():
    s = SearchDirtyState(root_mapping_id=1)
    assert s.replay_attempts == 0
    assert s.increment_replay_attempt() == 1
    assert s.increment_replay_attempt() == 2
    assert s.replay_attempts == 2


def test_mark_dirty_overwrites_previous_error():
    s = SearchDirtyState(root_mapping_id=1)
    s.mark_dirty("err1", "msg1", now=_NOW)
    s.mark_dirty("err2", "msg2", now=_NOW)
    assert s.last_error_code == "err2"
    assert s.last_error_message == "msg2"


def test_multi_root_isolation():
    s1 = SearchDirtyState(root_mapping_id=1)
    s2 = SearchDirtyState(root_mapping_id=2)
    s1.mark_dirty("err", now=_NOW)
    assert s1.needs_replay is True
    assert s2.needs_replay is False


def test_mark_dirty_default_now():
    before = datetime.now(timezone.utc)
    s = SearchDirtyState(root_mapping_id=1)
    s.mark_dirty("err")
    after = datetime.now(timezone.utc)
    assert before <= s.last_failure_at <= after


def test_mark_clean_default_now():
    before = datetime.now(timezone.utc)
    s = SearchDirtyState(root_mapping_id=1)
    s.mark_clean()
    after = datetime.now(timezone.utc)
    assert before <= s.last_success_at <= after


def test_has_error_false_after_clean():
    s = SearchDirtyState(root_mapping_id=1)
    s.mark_dirty("err", now=_NOW)
    assert s.has_error is True
    s.mark_clean(now=_NOW)
    assert s.has_error is False