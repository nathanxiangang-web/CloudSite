import sqlite3

import pytest

from cloudsite.database import (
    DatabaseRecoveryRequired,
    INDEX_REQUIRED_TABLES,
    STATE_REQUIRED_TABLES,
    validate_database_files,
)


def create_database(path, tables: set[str]) -> None:
    connection = sqlite3.connect(path)
    try:
        for table in sorted(tables):
            if table == "search_fts":
                connection.execute("CREATE VIRTUAL TABLE search_fts USING fts5(name)")
            else:
                connection.execute(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY)')
        connection.commit()
    finally:
        connection.close()


def test_clean_data_directory_is_a_fresh_install(tmp_path):
    assert validate_database_files(tmp_path) == {"state": "fresh", "index": "fresh"}
    assert not (tmp_path / "state.db").exists()
    assert not (tmp_path / "index.db").exists()


def test_state_loss_does_not_become_new_install(tmp_path):
    create_database(tmp_path / "index.db", INDEX_REQUIRED_TABLES)
    with pytest.raises(DatabaseRecoveryRequired) as error:
        validate_database_files(tmp_path)
    assert error.value.code == "STATE_RECOVERY_REQUIRED"
    assert "恢复备份" in str(error.value)
    assert not (tmp_path / "state.db").exists()


def test_state_schema_loss_requires_recovery(tmp_path):
    create_database(tmp_path / "state.db", {"system_settings"})
    with pytest.raises(DatabaseRecoveryRequired) as error:
        validate_database_files(tmp_path)
    assert error.value.code == "STATE_RECOVERY_REQUIRED"
    assert "缺少关键表" in str(error.value)


def test_index_loss_enters_recovery_without_touching_state(tmp_path):
    create_database(tmp_path / "state.db", STATE_REQUIRED_TABLES)
    before = (tmp_path / "state.db").read_bytes()
    assert validate_database_files(tmp_path) == {
        "state": "ready",
        "index": "recovery_required",
    }
    assert (tmp_path / "state.db").read_bytes() == before
    assert not (tmp_path / "index.db").exists()


def test_malformed_index_is_a_fatal_index_state(tmp_path):
    create_database(tmp_path / "state.db", STATE_REQUIRED_TABLES)
    (tmp_path / "index.db").write_bytes(b"not a sqlite database")
    with pytest.raises(DatabaseRecoveryRequired) as error:
        validate_database_files(tmp_path)
    assert error.value.code == "INDEX_RECOVERY_REQUIRED"
    assert "损坏" in str(error.value)


def test_complete_existing_databases_pass_preflight(tmp_path):
    create_database(tmp_path / "state.db", STATE_REQUIRED_TABLES)
    create_database(tmp_path / "index.db", INDEX_REQUIRED_TABLES)
    assert validate_database_files(tmp_path) == {"state": "ready", "index": "ready"}


def test_recreated_empty_state_is_not_accepted_for_existing_index(tmp_path):
    create_database(tmp_path / "state.db", STATE_REQUIRED_TABLES)
    create_database(tmp_path / "index.db", INDEX_REQUIRED_TABLES)
    connection = sqlite3.connect(tmp_path / "index.db")
    try:
        connection.execute("INSERT INTO folders(id) VALUES (1)")
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(DatabaseRecoveryRequired) as error:
        validate_database_files(tmp_path)
    assert error.value.code == "STATE_RECOVERY_REQUIRED"
    assert "实例身份" in str(error.value)
