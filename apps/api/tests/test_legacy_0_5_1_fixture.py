"""Fixture validation for the CloudSite 0.5.1 state.db SQL fixture.

The fixture at tests/fixtures/state-0.5.1.sql is a hand-written, reviewable
SQL dump whose schema and representative rows are derived from commit 4d69cb3
(feat: release CloudSite 0.5.1 user library and native video). These tests
load the SQL into a temporary SQLite database and verify:

1. Every declared legacy state table is present.
2. Each business entity has the expected representative row count.
3. Foreign-key integrity check returns no violations.
4. One stable resource ID is present and anchored to user data.

No production ORM metadata is used to build the schema; the SQL file is the
single source of truth for the 0.5.1 legacy shape.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "state-0.5.1.sql"

LEGACY_TABLES = (
    "alist_connections",
    "site_settings",
    "system_settings",
    "content_root_mappings",
    "download_events",
    "download_diagnostics",
    "operation_logs",
    "collections",
    "collection_items",
    "shares",
    "share_verify_attempts",
    "users",
    "user_sessions",
    "user_favorites",
    "user_resource_history",
    "user_playback_progress",
    "download_rate_limits",
    "resource_identities",
    "resource_identity_history",
)

STABLE_RESOURCE_ID = "fixture-resource-001"


def _load_fixture(tmp_path: Path) -> sqlite3.Connection:
    assert FIXTURE_PATH.exists(), f"fixture missing at {FIXTURE_PATH}"
    db_path = tmp_path / "legacy_state.db"
    connection = sqlite3.connect(str(db_path))
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(FIXTURE_PATH.read_text(encoding="utf-8"))
    connection.commit()
    return connection


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }


def test_fixture_file_carries_provenance_comment():
    text = FIXTURE_PATH.read_text(encoding="utf-8")
    assert "4d69cb3" in text, "provenance comment must name commit 4d69cb3"
    assert "CloudSite 0.5.1" in text, "provenance comment must name release 0.5.1"


def test_fixture_loads_into_clean_sqlite_database(tmp_path):
    connection = _load_fixture(tmp_path)
    try:
        assert _table_names(connection) == set(LEGACY_TABLES)
    finally:
        connection.close()


@pytest.mark.parametrize("table", LEGACY_TABLES)
def test_legacy_table_present(tmp_path, table):
    connection = _load_fixture(tmp_path)
    try:
        assert table in _table_names(connection)
    finally:
        connection.close()


def test_alist_connection_has_representative_row(tmp_path):
    connection = _load_fixture(tmp_path)
    try:
        row = connection.execute(
            "SELECT id, base_url, provider_type, enabled FROM alist_connections WHERE id = 1"
        ).fetchone()
        assert row is not None
        assert row[0] == 1
        assert row[1] == "https://alist.fixture.example"
        assert row[2] == "generic_alist"
        assert row[3] == 1
    finally:
        connection.close()


def test_content_root_mappings_have_representative_rows(tmp_path):
    connection = _load_fixture(tmp_path)
    try:
        count = connection.execute(
            "SELECT COUNT(*) FROM content_root_mappings"
        ).fetchone()[0]
        assert count == 2
    finally:
        connection.close()


def test_users_have_representative_rows(tmp_path):
    connection = _load_fixture(tmp_path)
    try:
        count = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        assert count == 2
        usernames = {
            row[0]
            for row in connection.execute("SELECT username FROM users ORDER BY id")
        }
        assert usernames == {"fixture-user", "fixture-admin"}
    finally:
        connection.close()


def test_user_favorites_have_representative_rows(tmp_path):
    connection = _load_fixture(tmp_path)
    try:
        count = connection.execute("SELECT COUNT(*) FROM user_favorites").fetchone()[0]
        assert count == 2
    finally:
        connection.close()


def test_user_resource_history_has_representative_row(tmp_path):
    connection = _load_fixture(tmp_path)
    try:
        count = connection.execute(
            "SELECT COUNT(*) FROM user_resource_history"
        ).fetchone()[0]
        assert count == 1
    finally:
        connection.close()


def test_user_playback_progress_has_representative_row(tmp_path):
    connection = _load_fixture(tmp_path)
    try:
        count = connection.execute(
            "SELECT COUNT(*) FROM user_playback_progress"
        ).fetchone()[0]
        assert count == 1
    finally:
        connection.close()


def test_shares_have_representative_row(tmp_path):
    connection = _load_fixture(tmp_path)
    try:
        count = connection.execute("SELECT COUNT(*) FROM shares").fetchone()[0]
        assert count == 1
        token = connection.execute(
            "SELECT token FROM shares WHERE object_id = ?", (STABLE_RESOURCE_ID,)
        ).fetchone()
        assert token is not None
        assert token[0] == "fixture-share-token-0001"
    finally:
        connection.close()


def test_collections_and_members_have_representative_rows(tmp_path):
    connection = _load_fixture(tmp_path)
    try:
        collection_count = connection.execute(
            "SELECT COUNT(*) FROM collections"
        ).fetchone()[0]
        item_count = connection.execute(
            "SELECT COUNT(*) FROM collection_items"
        ).fetchone()[0]
        assert collection_count == 1
        assert item_count == 2
    finally:
        connection.close()


def test_resource_identities_have_representative_rows(tmp_path):
    connection = _load_fixture(tmp_path)
    try:
        count = connection.execute(
            "SELECT COUNT(*) FROM resource_identities"
        ).fetchone()[0]
        assert count == 2
    finally:
        connection.close()


def test_stable_resource_id_exists(tmp_path):
    connection = _load_fixture(tmp_path)
    try:
        row = connection.execute(
            "SELECT resource_id, status, last_name FROM resource_identities "
            "WHERE resource_id = ?",
            (STABLE_RESOURCE_ID,),
        ).fetchone()
        assert row is not None
        assert row[0] == STABLE_RESOURCE_ID
        assert row[1] == "active"
        assert row[2] == "cloudsite-0.5.1"
    finally:
        connection.close()


def test_stable_resource_id_anchors_user_data(tmp_path):
    connection = _load_fixture(tmp_path)
    try:
        favorite = connection.execute(
            "SELECT 1 FROM user_favorites WHERE resource_id = ? LIMIT 1",
            (STABLE_RESOURCE_ID,),
        ).fetchone()
        assert favorite is not None
        history = connection.execute(
            "SELECT 1 FROM user_resource_history WHERE resource_id = ? LIMIT 1",
            (STABLE_RESOURCE_ID,),
        ).fetchone()
        assert history is not None
        share = connection.execute(
            "SELECT 1 FROM shares WHERE object_id = ? LIMIT 1",
            (STABLE_RESOURCE_ID,),
        ).fetchone()
        assert share is not None
        member = connection.execute(
            "SELECT 1 FROM collection_items WHERE resource_id = ? LIMIT 1",
            (STABLE_RESOURCE_ID,),
        ).fetchone()
        assert member is not None
    finally:
        connection.close()


def test_foreign_key_check_returns_no_violations(tmp_path):
    connection = _load_fixture(tmp_path)
    try:
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        assert violations == [], f"foreign-key violations: {violations}"
    finally:
        connection.close()


def test_required_state_identity_tables_have_rows(tmp_path):
    connection = _load_fixture(tmp_path)
    try:
        for table in ("users", "alist_connections", "site_settings", "system_settings"):
            count = connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            assert count > 0, f"{table} must have at least one identity row"
    finally:
        connection.close()


def test_fixture_contains_no_real_secret_material():
    text = FIXTURE_PATH.read_text(encoding="utf-8")
    forbidden = (
        "nathxo@outlook.com",
        "BEGIN PRIVATE KEY",
        "-----BEGIN",
    )
    for token in forbidden:
        assert token not in text, f"forbidden token present in fixture: {token}"
    assert "fixture-hash-not-a-real-password" in text
    assert "fixture-ciphertext-not-a-real-secret" in text
