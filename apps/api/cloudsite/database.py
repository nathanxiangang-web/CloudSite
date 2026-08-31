from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings


class StateBase(DeclarativeBase):
    pass


class IndexBase(DeclarativeBase):
    pass


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
        share_columns = await connection.exec_driver_sql("PRAGMA table_info(shares)")
        if "last_accessed_at" not in {row[1] for row in share_columns.fetchall()}:
            await connection.exec_driver_sql(
                "ALTER TABLE shares ADD COLUMN last_accessed_at DATETIME"
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
