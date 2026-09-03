import sqlite3
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings


class StateBase(DeclarativeBase):
    pass


class IndexBase(DeclarativeBase):
    pass


class DatabaseRecoveryRequired(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


STATE_REQUIRED_TABLES = {
    "alist_connections",
    "site_settings",
    "system_settings",
    "users",
    "user_sessions",
}
INDEX_REQUIRED_TABLES = {
    "folders",
    "resources",
    "sync_runs",
}


def _read_only_database_check(path: Path, required_tables: set[str], code: str) -> None:
    try:
        connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        try:
            quick_check = connection.execute("PRAGMA quick_check(1)").fetchone()
            if not quick_check or quick_check[0] != "ok":
                raise DatabaseRecoveryRequired(code, f"{path.name} 完整性检查失败")
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
                )
            }
        finally:
            connection.close()
    except DatabaseRecoveryRequired:
        raise
    except (OSError, sqlite3.DatabaseError) as exc:
        raise DatabaseRecoveryRequired(code, f"{path.name} 无法读取或已损坏") from exc
    missing = sorted(required_tables - tables)
    if missing:
        raise DatabaseRecoveryRequired(code, f"{path.name} 缺少关键表：{', '.join(missing)}")


def _database_has_rows(path: Path, tables: tuple[str, ...]) -> bool:
    try:
        connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        try:
            return any(
                connection.execute(f'SELECT 1 FROM "{table}" LIMIT 1').fetchone() is not None
                for table in tables
            )
        finally:
            connection.close()
    except (OSError, sqlite3.DatabaseError) as exc:
        raise DatabaseRecoveryRequired(
            "STATE_RECOVERY_REQUIRED",
            "无法确认数据库实例身份；请先恢复 state.db 备份",
        ) from exc


def validate_database_files(data_dir: Path | None = None) -> dict[str, str]:
    root = (data_dir or settings.data_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    state_path = root / "state.db"
    index_path = root / "index.db"

    if not state_path.exists():
        traces = [
            item
            for item in root.iterdir()
            if item.name not in {"state.db-shm", "state.db-wal"}
        ]
        if index_path.exists() or traces:
            raise DatabaseRecoveryRequired(
                "STATE_RECOVERY_REQUIRED",
                "state.db 丢失，但数据目录中存在既有实例痕迹；请恢复备份",
            )
        return {"state": "fresh", "index": "fresh"}

    _read_only_database_check(state_path, STATE_REQUIRED_TABLES, "STATE_RECOVERY_REQUIRED")
    if not index_path.exists():
        return {"state": "ready", "index": "recovery_required"}
    _read_only_database_check(index_path, INDEX_REQUIRED_TABLES, "INDEX_RECOVERY_REQUIRED")
    state_has_identity = _database_has_rows(
        state_path,
        ("users", "alist_connections", "site_settings", "system_settings"),
    )
    index_has_content = _database_has_rows(index_path, ("folders", "resources", "sync_runs"))
    if index_has_content and not state_has_identity:
        raise DatabaseRecoveryRequired(
            "STATE_RECOVERY_REQUIRED",
            "index.db 包含既有索引，但 state.db 没有实例身份数据；请恢复 state.db 备份",
        )
    return {"state": "ready", "index": "ready"}


state_engine = create_async_engine(settings.state_db_url)
index_engine = create_async_engine(settings.index_db_url)
StateSession = async_sessionmaker(state_engine, expire_on_commit=False, class_=AsyncSession)
IndexSession = async_sessionmaker(index_engine, expire_on_commit=False, class_=AsyncSession)


for engine in (state_engine, index_engine):
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA wal_autocheckpoint=1000")
        cursor.close()


async def init_databases() -> None:
    from . import models  # noqa: F401

    async with state_engine.begin() as connection:
        await connection.run_sync(StateBase.metadata.create_all)
        columns = await connection.exec_driver_sql("PRAGMA table_info(system_settings)")
        if "value_type" not in {row[1] for row in columns.fetchall()}:
            await connection.exec_driver_sql(
                "ALTER TABLE system_settings ADD COLUMN value_type VARCHAR(20) NOT NULL DEFAULT 'string'"
            )
        download_columns = await connection.exec_driver_sql("PRAGMA table_info(download_events)")
        if "source" not in {row[1] for row in download_columns.fetchall()}:
            await connection.exec_driver_sql(
                "ALTER TABLE download_events ADD COLUMN source VARCHAR(20) NOT NULL DEFAULT 'public'"
            )
        alist_columns = await connection.exec_driver_sql("PRAGMA table_info(alist_connections)")
        if "base_path" not in {row[1] for row in alist_columns.fetchall()}:
            await connection.exec_driver_sql(
                "ALTER TABLE alist_connections ADD COLUMN base_path VARCHAR(1000) NOT NULL DEFAULT '/'"
            )
        collection_columns = await connection.exec_driver_sql("PRAGMA table_info(collections)")
        if "status" not in {row[1] for row in collection_columns.fetchall()}:
            await connection.exec_driver_sql(
                "ALTER TABLE collections ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'active'"
            )
        site_columns = await connection.exec_driver_sql("PRAGMA table_info(site_settings)")
        if "share_image_name" not in {row[1] for row in site_columns.fetchall()}:
            await connection.exec_driver_sql(
                "ALTER TABLE site_settings ADD COLUMN share_image_name VARCHAR(255) NOT NULL DEFAULT ''"
            )
        share_columns = await connection.exec_driver_sql("PRAGMA table_info(shares)")
        share_column_names = {row[1] for row in share_columns.fetchall()}
        for column, definition in (
            ("creator_user_id", "INTEGER"),
            ("last_accessed_at", "DATETIME"),
            ("access_mode", "VARCHAR(20) NOT NULL DEFAULT 'code'"),
            ("code_hash", "VARCHAR(64)"),
            ("code_version", "INTEGER NOT NULL DEFAULT 0"),
            ("cancelled_at", "DATETIME"),
            ("cancel_reason", "VARCHAR(30)"),
            ("view_count", "INTEGER NOT NULL DEFAULT 0"),
            ("download_count", "INTEGER NOT NULL DEFAULT 0"),
            ("last_downloaded_at", "DATETIME"),
        ):
            if column not in share_column_names:
                await connection.exec_driver_sql(f"ALTER TABLE shares ADD COLUMN {column} {definition}")
        await connection.exec_driver_sql(
            "UPDATE shares SET view_count = access_count WHERE view_count = 0 AND access_count > 0"
        )
        await connection.exec_driver_sql(
            "UPDATE shares SET access_mode = 'code' WHERE access_mode IS NULL OR access_mode = ''"
        )
        await connection.exec_driver_sql(
            "UPDATE shares SET code_version = 0 WHERE code_version IS NULL"
        )
        await connection.exec_driver_sql(
            "UPDATE shares SET download_count = 0 WHERE download_count IS NULL"
        )
        await connection.exec_driver_sql(
            "UPDATE shares SET view_count = 0 WHERE view_count IS NULL"
        )
        await connection.exec_driver_sql(
            "UPDATE shares SET cancelled_at = CURRENT_TIMESTAMP WHERE enabled = 0 AND cancelled_at IS NULL"
        )
        await connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_shares_access_mode ON shares (access_mode)"
        )
        await connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_shares_creator_user_id ON shares (creator_user_id)"
        )
        await connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_shares_cancelled_at ON shares (cancelled_at)"
        )
        await connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_shares_last_downloaded_at ON shares (last_downloaded_at)"
        )
        await connection.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS share_verify_attempts ("
            "id INTEGER NOT NULL PRIMARY KEY, "
            "share_token VARCHAR(64) NOT NULL, "
            "ip_hash VARCHAR(64) NOT NULL, "
            "fail_count INTEGER NOT NULL DEFAULT 0, "
            "window_started_at DATETIME NOT NULL, "
            "challenge_required_until DATETIME, "
            "updated_at DATETIME NOT NULL, "
            "UNIQUE (share_token, ip_hash))"
        )
        await connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_share_verify_attempts_share_token ON share_verify_attempts (share_token)"
        )
        await connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_share_verify_attempts_ip_hash ON share_verify_attempts (ip_hash)"
        )
        await connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_share_verify_attempts_challenge_required_until ON share_verify_attempts (challenge_required_until)"
        )
        for table, column, definition in (
            ("users", "disabled_at", "DATETIME"),
            ("users", "deleted_at", "DATETIME"),
            ("users", "created_by_admin", "BOOLEAN NOT NULL DEFAULT 0"),
            ("user_sessions", "created_ip_hash", "VARCHAR(64)"),
            ("user_sessions", "user_agent_hash", "VARCHAR(64)"),
        ):
            table_columns = await connection.exec_driver_sql(f"PRAGMA table_info({table})")
            if column not in {row[1] for row in table_columns.fetchall()}:
                await connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        await connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_users_deleted_at ON users (deleted_at)"
        )
        await connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_users_disabled_at ON users (disabled_at)"
        )
    async with index_engine.begin() as connection:
        await connection.run_sync(IndexBase.metadata.create_all)
        for table, column, definition in (
            ("folders", "root_mapping_id", "INTEGER"),
            ("folders", "missing_streak", "INTEGER NOT NULL DEFAULT 0"),
            ("folders", "missing_candidate_at", "DATETIME"),
            ("folders", "last_seen_run_id", "INTEGER"),
            ("folders", "missing_last_observed_cycle_id", "INTEGER"),
            ("resources", "root_mapping_id", "INTEGER"),
            ("resources", "missing_streak", "INTEGER NOT NULL DEFAULT 0"),
            ("resources", "missing_candidate_at", "DATETIME"),
            ("resources", "last_seen_run_id", "INTEGER"),
            ("resources", "missing_last_observed_cycle_id", "INTEGER"),
            ("sync_runs", "duration_ms", "INTEGER NOT NULL DEFAULT 0"),
            ("sync_runs", "current_path", "VARCHAR(1500) NOT NULL DEFAULT ''"),
            ("sync_runs", "roots_total", "INTEGER NOT NULL DEFAULT 0"),
            ("sync_runs", "roots_completed", "INTEGER NOT NULL DEFAULT 0"),
            ("sync_runs", "roots_failed", "INTEGER NOT NULL DEFAULT 0"),
            ("sync_runs", "list_requests", "INTEGER NOT NULL DEFAULT 0"),
        ):
            columns = await connection.exec_driver_sql(f"PRAGMA table_info({table})")
            if column not in {row[1] for row in columns.fetchall()}:
                await connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        expected_search_columns = [
            "object_id", "object_type", "name", "extension", "content_type",
            "description", "tags", "breadcrumb_text",
        ]
        search_columns = await connection.exec_driver_sql("PRAGMA table_info(search_fts)")
        if [row[1] for row in search_columns.fetchall()] not in ([], expected_search_columns):
            await connection.exec_driver_sql("DROP TABLE search_fts")
        await connection.exec_driver_sql(
            "CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5("
            "object_id UNINDEXED, object_type UNINDEXED, name, extension, "
            "content_type UNINDEXED, description, tags, breadcrumb_text, tokenize='unicode61 remove_diacritics 2')"
        )
        search_count = await connection.exec_driver_sql("SELECT COUNT(*) FROM search_fts")
        if int(search_count.scalar_one()) == 0:
            await connection.exec_driver_sql(
                "INSERT INTO search_fts(object_id, object_type, name, extension, content_type, description, tags, breadcrumb_text) "
                "SELECT id, 'folder', name, '', content_type, '', '', path FROM folders WHERE status = 'active'"
            )
            await connection.exec_driver_sql(
                "INSERT INTO search_fts(object_id, object_type, name, extension, content_type, description, tags, breadcrumb_text) "
                "SELECT id, 'resource', name, extension, content_type, '', '', path FROM resources WHERE status = 'active'"
            )
