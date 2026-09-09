"""CloudSite schema migration framework.

显式 schema_version + 单向 migration chain + 幂等。
- state.db schema_version 存于 system_settings(key='schema_version')
- index.db schema_version 存于 _schema_meta(key='schema_version')

1.0 baseline: 现有 init_databases 的幂等 ALTER 逻辑归为 schema_version 1。
未来新增字段追加 Migration(from=N, to=N+1) 并注册到 chain，保持只向前迁移。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncConnection

CURRENT_SCHEMA_VERSION = 5


@dataclass(frozen=True, slots=True)
class Migration:
    """一条单向 schema migration，upgrade 必须幂等。"""

    id: str
    from_version: int
    to_version: int
    upgrade: Callable[[AsyncConnection], Awaitable[None]]


async def get_state_schema_version(conn: AsyncConnection) -> int:
    row = await conn.exec_driver_sql(
        "SELECT value FROM system_settings WHERE key='schema_version'"
    )
    r = row.fetchone()
    return int(r[0]) if r else 0


async def set_state_schema_version(conn: AsyncConnection, version: int) -> None:
    await conn.exec_driver_sql(
        "INSERT OR REPLACE INTO system_settings(key, value, value_type, updated_at) "
        "VALUES('schema_version', ?, 'integer', CURRENT_TIMESTAMP)",
        (str(version),),
    )


async def get_index_schema_version(conn: AsyncConnection) -> int:
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS _schema_meta("
        "key VARCHAR(40) PRIMARY KEY, value VARCHAR(40) NOT NULL)"
    )
    row = await conn.exec_driver_sql(
        "SELECT value FROM _schema_meta WHERE key='schema_version'"
    )
    r = row.fetchone()
    return int(r[0]) if r else 0


async def set_index_schema_version(conn: AsyncConnection, version: int) -> None:
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS _schema_meta("
        "key VARCHAR(40) PRIMARY KEY, value VARCHAR(40) NOT NULL)"
    )
    await conn.exec_driver_sql(
        "INSERT OR REPLACE INTO _schema_meta(key, value) "
        "VALUES('schema_version', ?)",
        (str(version),),
    )


async def run_migrations(
    conn: AsyncConnection,
    chain: list[Migration],
    get_version: Callable[[AsyncConnection], Awaitable[int]],
    set_version: Callable[[AsyncConnection, int], Awaitable[None]],
) -> tuple[int, list[str]]:
    """跑单向 migration chain，返回 (最终版本, 已应用 migration id 列表)。

    只向前：对 from_version <= cur < to_version 的 migration 依次执行。
    每条 upgrade 必须幂等；失败抛异常则调用方不应启动 Scheduler/Sync。
    """
    cur = await get_version(conn)
    applied: list[str] = []
    for m in chain:
        if m.from_version <= cur < m.to_version:
            await m.upgrade(conn)
            cur = m.to_version
            await set_version(conn, cur)
            applied.append(m.id)
    return cur, applied


async def state_v1_to_v2_upgrade(conn: AsyncConnection) -> None:
    """Schema v1 → v2：投稿与通知表 + 索引，幂等。"""
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS submissions("
        "id INTEGER PRIMARY KEY,"
        "user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,"
        "resource_name VARCHAR(120) NOT NULL,"
        "resource_type VARCHAR(20) NOT NULL,"
        "description TEXT DEFAULT '',"
        "source_url VARCHAR(1000) DEFAULT '',"
        "download_url VARCHAR(2000) DEFAULT '',"
        "copyright_note TEXT DEFAULT '',"
        "note TEXT DEFAULT '',"
        "status VARCHAR(20) DEFAULT 'pending' NOT NULL,"
        "admin_note TEXT DEFAULT '',"
        "reviewed_by VARCHAR(100) DEFAULT '',"
        "reviewed_at DATETIME,"
        "created_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
    )
    await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_submissions_user_id ON submissions (user_id)")
    await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_submissions_status ON submissions (status)")
    submission_cols = await conn.exec_driver_sql("PRAGMA table_info(submissions)")
    if "published_resource_id" not in {row[1] for row in submission_cols.fetchall()}:
        await conn.exec_driver_sql("ALTER TABLE submissions ADD COLUMN published_resource_id VARCHAR(64)")
    await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_submissions_published_resource_id ON submissions (published_resource_id)")
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS notifications("
        "id INTEGER PRIMARY KEY,"
        "user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,"
        "title VARCHAR(200) NOT NULL,"
        "body TEXT DEFAULT '',"
        "level VARCHAR(20) DEFAULT 'info' NOT NULL,"
        "pinned BOOLEAN DEFAULT 0 NOT NULL,"
        "enabled BOOLEAN DEFAULT 1 NOT NULL,"
        "source VARCHAR(30) DEFAULT 'manual' NOT NULL,"
        "published_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        "expires_at DATETIME,"
        "created_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
    )
    await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_notifications_user_id ON notifications (user_id)")
    await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_notifications_level ON notifications (level)")
    await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_notifications_enabled ON notifications (enabled)")
    await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_notifications_published_at ON notifications (published_at)")


async def state_v2_to_v3_upgrade(conn: AsyncConnection) -> None:
    """Schema v2 → v3：FolderIdentity / FolderIdentityHistory 表，幂等。"""
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS folder_identities("
        "folder_id VARCHAR(64) PRIMARY KEY,"
        "current_path VARCHAR(1500),"
        "root_mapping_id INTEGER,"
        "status VARCHAR(30) DEFAULT 'active',"
        "first_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        "last_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        "last_name VARCHAR(500) DEFAULT '',"
        "identity_fingerprint VARCHAR(64),"
        "fingerprint_version INTEGER DEFAULT 1,"
        "created_from VARCHAR(30) DEFAULT 'new_folder',"
        "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
    )
    await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_folder_identities_current_path ON folder_identities (current_path)")
    await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_folder_identities_root_mapping_id ON folder_identities (root_mapping_id)")
    await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_folder_identities_status ON folder_identities (status)")
    await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_folder_identities_identity_fingerprint ON folder_identities (identity_fingerprint)")
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS folder_identity_histories("
        "id INTEGER PRIMARY KEY,"
        "folder_id VARCHAR(64) NOT NULL REFERENCES folder_identities(folder_id) ON DELETE RESTRICT,"
        "path VARCHAR(1500),"
        "event_type VARCHAR(30),"
        "first_observed_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        "last_observed_at DATETIME DEFAULT CURRENT_TIMESTAMP,"
        "from_path VARCHAR(1500),"
        "to_path VARCHAR(1500),"
        "cycle_id INTEGER,"
        "created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
    )
    await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_folder_identity_histories_folder_id ON folder_identity_histories (folder_id)")
    await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_folder_identity_histories_event_type ON folder_identity_histories (event_type)")
    await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_folder_identity_histories_cycle_id ON folder_identity_histories (cycle_id)")


async def state_v3_to_v4_upgrade(conn: AsyncConnection) -> None:
    """Schema v3 -> v4: Catalog core state tables, idempotent.

    Adds catalog_entries, catalog_releases, catalog_assets, catalog_locations
    to state.db per docs/catalog-v1.1-contract.md sections 3.1-3.4. Foreign
    keys are declared only within state.db. catalog_locations.resource_id is a
    plain stable ID reference to index.db resources.id (cross-database, no SQL
    foreign key). The catalog_releases.slug default 'unversioned' provides an
    explicit default unversioned release representation.
    """
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS catalog_entries("
        "entry_id VARCHAR(35) PRIMARY KEY,"
        "content_type VARCHAR(40) NOT NULL,"
        "slug VARCHAR(160) NOT NULL UNIQUE,"
        "title VARCHAR(200) NOT NULL,"
        "summary TEXT DEFAULT '',"
        "description TEXT DEFAULT '',"
        "cover_resource_id VARCHAR(64),"
        "status VARCHAR(20) NOT NULL DEFAULT 'draft',"
        "revision INTEGER NOT NULL DEFAULT 1,"
        "sort_order INTEGER DEFAULT 0,"
        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        "published_at DATETIME)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_entries_status ON catalog_entries (status)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_entries_content_type ON catalog_entries (content_type)"
    )
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS catalog_releases("
        "release_id VARCHAR(35) PRIMARY KEY,"
        "entry_id VARCHAR(35) NOT NULL REFERENCES catalog_entries(entry_id) ON DELETE CASCADE,"
        "slug VARCHAR(160) NOT NULL DEFAULT 'unversioned',"
        "title VARCHAR(200) NOT NULL,"
        "release_notes TEXT DEFAULT '',"
        "status VARCHAR(20) NOT NULL DEFAULT 'draft',"
        "sort_order INTEGER DEFAULT 0,"
        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        "published_at DATETIME,"
        "UNIQUE (entry_id, slug))"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_releases_entry_id ON catalog_releases (entry_id)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_releases_status ON catalog_releases (status)"
    )
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS catalog_assets("
        "asset_id VARCHAR(35) PRIMARY KEY,"
        "release_id VARCHAR(35) NOT NULL REFERENCES catalog_releases(release_id) ON DELETE CASCADE,"
        "slug VARCHAR(160) NOT NULL,"
        "display_name VARCHAR(500) NOT NULL,"
        "platform VARCHAR(40) DEFAULT '',"
        "kind VARCHAR(40) DEFAULT 'file',"
        "checksum VARCHAR(200),"
        "checksum_algorithm VARCHAR(20),"
        "size BIGINT,"
        "status VARCHAR(20) NOT NULL DEFAULT 'active',"
        "sort_order INTEGER DEFAULT 0,"
        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        "UNIQUE (release_id, slug))"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_assets_release_id ON catalog_assets (release_id)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_assets_status ON catalog_assets (status)"
    )
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS catalog_locations("
        "location_id VARCHAR(35) PRIMARY KEY,"
        "asset_id VARCHAR(35) NOT NULL REFERENCES catalog_assets(asset_id) ON DELETE CASCADE,"
        "resource_id VARCHAR(64) NOT NULL,"
        "root_mapping_id INTEGER,"
        "label VARCHAR(100) DEFAULT '',"
        "is_primary BOOLEAN DEFAULT 0 NOT NULL,"
        "status VARCHAR(20) NOT NULL DEFAULT 'active',"
        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        "UNIQUE (asset_id, resource_id))"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_locations_asset_id ON catalog_locations (asset_id)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_locations_resource_id ON catalog_locations (resource_id)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_locations_root_mapping_id ON catalog_locations (root_mapping_id)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_locations_status ON catalog_locations (status)"
    )


async def state_v4_to_v5_upgrade(conn: AsyncConnection) -> None:
    """Schema v4 -> v5: Catalog metadata overlay (tags, entry-tag membership,
    typed relations, append-only revision history), idempotent.

    Adds catalog_tags, catalog_entry_tags, catalog_relations, and
    catalog_revisions to state.db per docs/catalog-v1.1-contract.md sections
    3.5-3.8. Enforces:
    - normalized tag slug uniqueness (UNIQUE on catalog_tags.slug)
    - unique entry-tag membership (UNIQUE (tag_id, target_type, target_id))
    - typed relation uniqueness (UNIQUE (from_entry_id, to_entry_id, relation_type))
    - no direct self-relation (CHECK from_entry_id != to_entry_id)
    - append-only revision rows (SQLite triggers reject UPDATE/DELETE)

    Revision rows store structured before/after snapshots, a reversible diff,
    base/resulting revision numbers, summary, actor, source, and timestamps.
    They never store credentials: catalog metadata contains no credential
    fields, and the snapshot columns are restricted to catalog entity fields.
    Foreign keys are declared only within state.db.
    """
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS catalog_tags("
        "tag_id VARCHAR(35) PRIMARY KEY,"
        "slug VARCHAR(60) NOT NULL UNIQUE,"
        "display_name VARCHAR(100) NOT NULL,"
        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        "CHECK (slug = lower(slug)))"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_tags_slug ON catalog_tags (slug)"
    )
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS catalog_entry_tags("
        "tag_id VARCHAR(35) NOT NULL REFERENCES catalog_tags(tag_id) ON DELETE CASCADE,"
        "target_type VARCHAR(20) NOT NULL,"
        "target_id VARCHAR(35) NOT NULL,"
        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        "UNIQUE (tag_id, target_type, target_id))"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_entry_tags_tag_id ON catalog_entry_tags (tag_id)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_entry_tags_target ON catalog_entry_tags (target_type, target_id)"
    )
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS catalog_relations("
        "relation_id VARCHAR(35) PRIMARY KEY,"
        "from_entry_id VARCHAR(35) NOT NULL REFERENCES catalog_entries(entry_id) ON DELETE CASCADE,"
        "to_entry_id VARCHAR(35) NOT NULL REFERENCES catalog_entries(entry_id) ON DELETE CASCADE,"
        "relation_type VARCHAR(40) NOT NULL,"
        "note TEXT DEFAULT '',"
        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        "UNIQUE (from_entry_id, to_entry_id, relation_type),"
        "CHECK (from_entry_id != to_entry_id))"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_relations_from_entry_id ON catalog_relations (from_entry_id)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_relations_to_entry_id ON catalog_relations (to_entry_id)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_relations_relation_type ON catalog_relations (relation_type)"
    )
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS catalog_revisions("
        "revision_id VARCHAR(35) PRIMARY KEY,"
        "target_type VARCHAR(20) NOT NULL,"
        "target_id VARCHAR(35) NOT NULL,"
        "action VARCHAR(40) NOT NULL,"
        "actor VARCHAR(100) NOT NULL,"
        "source VARCHAR(40) NOT NULL DEFAULT 'admin',"
        "base_revision INTEGER,"
        "resulting_revision INTEGER,"
        "summary TEXT DEFAULT '',"
        "before_json TEXT DEFAULT '',"
        "after_json TEXT DEFAULT '',"
        "diff_json TEXT DEFAULT '',"
        "payload_json TEXT DEFAULT '{}',"
        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_revisions_target ON catalog_revisions (target_type, target_id)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_revisions_action ON catalog_revisions (action)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_revisions_actor ON catalog_revisions (actor)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_revisions_created_at ON catalog_revisions (created_at)"
    )
    # Append-only enforcement: reject UPDATE and DELETE on revision rows.
    # A later rollback is represented as a new revision row, never an edit.
    await conn.exec_driver_sql(
        "CREATE TRIGGER IF NOT EXISTS catalog_revisions_no_update "
        "BEFORE UPDATE ON catalog_revisions "
        "BEGIN "
        "SELECT RAISE(ABORT, 'catalog_revisions is append-only: UPDATE is forbidden'); "
        "END"
    )
    await conn.exec_driver_sql(
        "CREATE TRIGGER IF NOT EXISTS catalog_revisions_no_delete "
        "BEFORE DELETE ON catalog_revisions "
        "BEGIN "
        "SELECT RAISE(ABORT, 'catalog_revisions is append-only: DELETE is forbidden'); "
        "END"
    )



STATE_MIGRATIONS: list[Migration] = [
    Migration(id="state_v1_to_v2", from_version=1, to_version=2, upgrade=state_v1_to_v2_upgrade),
    Migration(id="state_v2_to_v3", from_version=2, to_version=3, upgrade=state_v2_to_v3_upgrade),
    Migration(id="state_v3_to_v4", from_version=3, to_version=4, upgrade=state_v3_to_v4_upgrade),
    Migration(id="state_v4_to_v5", from_version=4, to_version=5, upgrade=state_v4_to_v5_upgrade),
]
