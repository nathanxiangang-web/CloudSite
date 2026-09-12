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

CURRENT_SCHEMA_VERSION = 24


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

    Adds catalog_tags, catalog_tag_assignments, catalog_relations, and
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
        "CREATE TABLE IF NOT EXISTS catalog_tag_assignments("
        "tag_id VARCHAR(35) NOT NULL REFERENCES catalog_tags(tag_id) ON DELETE CASCADE,"
        "target_type VARCHAR(20) NOT NULL,"
        "target_id VARCHAR(35) NOT NULL,"
        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        "UNIQUE (tag_id, target_type, target_id),"
        "CHECK (target_type IN ('entry', 'release', 'asset')))"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_tag_assignments_tag_id ON catalog_tag_assignments (tag_id)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_tag_assignments_target ON catalog_tag_assignments (target_type, target_id)"
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
        "before_json TEXT DEFAULT '{}',"
        "after_json TEXT DEFAULT '{}',"
        "diff_json TEXT DEFAULT '{}',"
        "payload_json TEXT DEFAULT '{}',"
        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        "CHECK (target_type IN ('entry', 'release', 'asset', 'location', 'tag', 'relation')),"
        "CHECK (action IN ('create', 'update', 'delete', 'publish', 'unpublish', 'archive', 'disable')))"
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



async def state_v5_to_v6_upgrade(conn: AsyncConnection) -> None:
    """Schema v5 -> v6: Durable administrator sessions (admin_sessions), idempotent.

    Adds admin_sessions to state.db to back revocable administrator sessions.
    Stores only a SHA-256 hash of the opaque session token, never the raw token.
    Keeps administrator sessions separate from user_sessions.

    Columns:
    - session_token_hash: SHA-256 hex of the opaque token (raw token never stored)
    - principal: recorded administrator principal (e.g. username)
    - authority: verified upstream role or authority text; explicit textual
      evidence so later code can record the verified upstream role without
      guessing from an unverified numeric value
    - created_at / last_seen_at / expires_at / revoked_at: lifecycle timestamps
    - revocation_reason: short textual reason (logout, rebind, expiry,
      epoch_change, admin_force_revoke)
    - epoch: session epoch; compared against the configured administrator
      session epoch so an epoch change invalidates older sessions
    - created_ip_hash / user_agent_hash: optional hashed request metadata
    """
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS admin_sessions("
        "id INTEGER PRIMARY KEY,"
        "session_token_hash VARCHAR(64) NOT NULL UNIQUE,"
        "principal VARCHAR(200) NOT NULL,"
        "authority VARCHAR(100) NOT NULL DEFAULT '',"
        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        "last_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        "expires_at DATETIME NOT NULL,"
        "revoked_at DATETIME,"
        "revocation_reason VARCHAR(40) DEFAULT '',"
        "epoch INTEGER NOT NULL DEFAULT 1,"
        "created_ip_hash VARCHAR(64),"
        "user_agent_hash VARCHAR(64))"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_admin_sessions_session_token_hash "
        "ON admin_sessions (session_token_hash)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_admin_sessions_principal ON admin_sessions (principal)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_admin_sessions_expires_at ON admin_sessions (expires_at)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_admin_sessions_revoked_at ON admin_sessions (revoked_at)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_admin_sessions_epoch ON admin_sessions (epoch)"
    )





async def state_v6_to_v7_upgrade(conn: AsyncConnection) -> None:
    """Schema v6 -> v7: explicit release and asset delivery metadata, idempotent.

    Adds explicit, non-inferred metadata columns to catalog_releases and
    catalog_assets so callers can distinguish versions, channels, platforms,
    architectures, and package forms without parsing slugs or names.

    catalog_releases gains:
    - channel: explicit release channel (default 'unknown'; never inferred
      from slugs or names)
    - release_date: optional explicit release date (nullable)
    - is_recommended: explicit recommendation flag (default 0). At most one
      release per entry may be recommended, enforced by a partial unique index
      on entry_id WHERE is_recommended = 1. Recommendation never depends on
      version-string comparison.

    catalog_assets gains:
    - architecture: explicit architecture (default 'unknown'; never inferred)
    - package_type: explicit package form (default 'unknown'; never inferred)

    Existing C1 rows keep every current column, ID, and uniqueness rule. New
    columns use conservative defaults so unknown metadata stays 'unknown' and
    existing unversioned C1 releases remain valid without inference.
    """
    release_cols = await conn.exec_driver_sql("PRAGMA table_info(catalog_releases)")
    release_col_names = {row[1] for row in release_cols.fetchall()}
    if "channel" not in release_col_names:
        await conn.exec_driver_sql(
            "ALTER TABLE catalog_releases ADD COLUMN channel VARCHAR(20) NOT NULL DEFAULT 'unknown'"
        )
    if "release_date" not in release_col_names:
        await conn.exec_driver_sql(
            "ALTER TABLE catalog_releases ADD COLUMN release_date DATETIME"
        )
    if "is_recommended" not in release_col_names:
        await conn.exec_driver_sql(
            "ALTER TABLE catalog_releases ADD COLUMN is_recommended BOOLEAN NOT NULL DEFAULT 0"
        )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_releases_channel ON catalog_releases (channel)"
    )
    await conn.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_catalog_releases_one_recommended_per_entry "
        "ON catalog_releases (entry_id) WHERE is_recommended = 1"
    )

    asset_cols = await conn.exec_driver_sql("PRAGMA table_info(catalog_assets)")
    asset_col_names = {row[1] for row in asset_cols.fetchall()}
    if "architecture" not in asset_col_names:
        await conn.exec_driver_sql(
            "ALTER TABLE catalog_assets ADD COLUMN architecture VARCHAR(20) NOT NULL DEFAULT 'unknown'"
        )
    if "package_type" not in asset_col_names:
        await conn.exec_driver_sql(
            "ALTER TABLE catalog_assets ADD COLUMN package_type VARCHAR(40) NOT NULL DEFAULT 'unknown'"
        )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_assets_architecture ON catalog_assets (architecture)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_assets_package_type ON catalog_assets (package_type)"
    )


async def state_v7_to_v8_upgrade(conn: AsyncConnection) -> None:
    """Schema v7 -> v8: asset delivery metadata language and build_label, idempotent.

    Adds explicit language and build_label columns to catalog_assets so callers
    can distinguish language/locale and build provenance without parsing slugs
    or names. language defaults to 'unknown' (never inferred); build_label
    defaults to '' (free-form build provenance, e.g. CI run id or git sha).
    Existing v7 rows keep every current column and get conservative defaults.
    """
    asset_cols = await conn.exec_driver_sql("PRAGMA table_info(catalog_assets)")
    asset_col_names = {row[1] for row in asset_cols.fetchall()}
    if "language" not in asset_col_names:
        await conn.exec_driver_sql(
            "ALTER TABLE catalog_assets ADD COLUMN language VARCHAR(20) NOT NULL DEFAULT 'unknown'"
        )
    if "build_label" not in asset_col_names:
        await conn.exec_driver_sql(
            "ALTER TABLE catalog_assets ADD COLUMN build_label VARCHAR(120) NOT NULL DEFAULT ''"
        )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_assets_language ON catalog_assets (language)"
    )


async def state_v8_to_v9_upgrade(conn: AsyncConnection) -> None:
    """Schema v8 -> v9: Catalog search projection outbox, idempotent.

    Adds catalog_search_outbox to state.db to back the D1 resource-level search
    projection. Each row records an entry_id, the catalog revision that
    triggered the projection, and an action (upsert/delete). Consumers process
    pending rows (consumed_at IS NULL) in created_at order, project to
    index.db catalog_search_fts in the same index transaction as the
    applied_revision watermark, and only then mark consumed_at. Stale rows
    whose entry has since advanced to a higher revision are skipped (old
    revision never overwrites newer data); replay is idempotent because the
    watermark comparison skips already-applied revisions.
    """
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS catalog_search_outbox("
        "outbox_id VARCHAR(35) PRIMARY KEY,"
        "entry_id VARCHAR(35) NOT NULL,"
        "revision INTEGER NOT NULL,"
        "action VARCHAR(20) NOT NULL DEFAULT 'upsert',"
        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        "consumed_at DATETIME,"
        "CHECK (action IN ('upsert', 'delete')))"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_search_outbox_entry_id ON catalog_search_outbox (entry_id)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_search_outbox_pending ON catalog_search_outbox (created_at, outbox_id)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_search_outbox_consumed_at ON catalog_search_outbox (consumed_at)"
    )



async def state_v9_to_v10_upgrade(conn: AsyncConnection) -> None:
    """Schema v9 -> v10: C4 资源关注与更新通知，幂等。

    新增三张 state.db 表支撑 C4「关注条目 + 新版本通知」语义：
    - catalog_favorites：用户对 catalog 条目的关注关系（entry_id + user_id 唯一），
      与 user_favorites（文件级收藏）严格分离，指向 catalog_entries.entry_id。
    - catalog_subscriptions：更新通知订阅开关，关注时默认 notify_enabled=1，
      可独立退订（置 0）而保留关注。
    - catalog_release_notifications：按 (release_id, user_id) 唯一的去重幂等记录，
      确保 release 重复发布不重复通知同一用户。

    所有外键仅在 state.db 内声明；ondelete=CASCADE 随用户/条目/版本删除清理。
    """
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS catalog_favorites("
        "id INTEGER PRIMARY KEY,"
        "user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,"
        "entry_id VARCHAR(35) NOT NULL REFERENCES catalog_entries(entry_id) ON DELETE CASCADE,"
        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        "UNIQUE (user_id, entry_id))"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_favorites_user_id ON catalog_favorites (user_id)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_favorites_entry_id ON catalog_favorites (entry_id)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_favorites_user_created_at ON catalog_favorites (user_id, created_at)"
    )
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS catalog_subscriptions("
        "id INTEGER PRIMARY KEY,"
        "user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,"
        "entry_id VARCHAR(35) NOT NULL REFERENCES catalog_entries(entry_id) ON DELETE CASCADE,"
        "notify_enabled BOOLEAN NOT NULL DEFAULT 1,"
        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        "UNIQUE (user_id, entry_id))"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_subscriptions_user_id ON catalog_subscriptions (user_id)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_subscriptions_entry_id ON catalog_subscriptions (entry_id)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_subscriptions_entry_enabled ON catalog_subscriptions (entry_id, notify_enabled)"
    )
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS catalog_release_notifications("
        "id INTEGER PRIMARY KEY,"
        "release_id VARCHAR(35) NOT NULL REFERENCES catalog_releases(release_id) ON DELETE CASCADE,"
        "user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,"
        "notification_id INTEGER REFERENCES notifications(id) ON DELETE SET NULL,"
        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        "UNIQUE (release_id, user_id))"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_release_notifications_release_id ON catalog_release_notifications (release_id)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_release_notifications_user_id ON catalog_release_notifications (user_id)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_release_notifications_notification_id ON catalog_release_notifications (notification_id)"
    )



async def state_v10_to_v11_upgrade(conn: AsyncConnection) -> None:
    """Schema v10 -> v11: A2 整理建议表 catalog_suggestions，幂等。

    新增 catalog_suggestions 到 state.db，用于 A2 影子模式生成的候选草稿。
    与正式 catalog 内容（entries/releases/assets）分表存储，apply 时才写入
    正式内容。唯一约束 (source_file_id, file_fingerprint, parser_version,
    suggestion_kind) 保证相同输入指纹 + 解析器版本幂等：重跑不重复生成草稿。
    人工已确认的行（status IN ('applied','rejected')）在重跑时不会被覆盖，
    生成器跳过已存在行而非 upsert。撤销产生新修订，不删除底层文件。
    """
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS catalog_suggestions("
        "suggestion_id VARCHAR(35) PRIMARY KEY,"
        "source_file_id VARCHAR(64) NOT NULL,"
        "file_fingerprint VARCHAR(64) NOT NULL,"
        "parser_version VARCHAR(20) NOT NULL,"
        "suggestion_kind VARCHAR(30) NOT NULL,"
        "target_entry_id VARCHAR(35),"
        "target_release_id VARCHAR(35),"
        "target_asset_id VARCHAR(35),"
        "suggested_fields_json TEXT DEFAULT '{}',"
        "evidence_json TEXT DEFAULT '{}',"
        "confidence FLOAT DEFAULT 0.0,"
        "status VARCHAR(20) NOT NULL DEFAULT 'pending',"
        "reviewed_by VARCHAR(100) DEFAULT '',"
        "reviewed_at DATETIME,"
        "applied_at DATETIME,"
        "applied_revision_id VARCHAR(35),"
        "reject_reason TEXT DEFAULT '',"
        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        "UNIQUE (source_file_id, file_fingerprint, parser_version, suggestion_kind),"
        "CHECK (suggestion_kind IN ('new_entry', 'new_release', 'asset', 'candidate_duplicate', 'conflict')),"
        "CHECK (status IN ('pending', 'reviewed', 'applied', 'rejected')))"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_suggestions_source_file_id ON catalog_suggestions (source_file_id)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_suggestions_file_fingerprint ON catalog_suggestions (file_fingerprint)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_suggestions_suggestion_kind ON catalog_suggestions (suggestion_kind)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_suggestions_status ON catalog_suggestions (status)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_suggestions_target_entry_id ON catalog_suggestions (target_entry_id)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_suggestions_target_release_id ON catalog_suggestions (target_release_id)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_suggestions_target_asset_id ON catalog_suggestions (target_asset_id)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_suggestions_kind_status ON catalog_suggestions (suggestion_kind, status)"
    )



async def state_v11_to_v12_upgrade(conn: AsyncConnection) -> None:
    """Schema v11 -> v12: B1 站点呈现配置表 site_presentation 与历史快照表
    site_presentation_revisions，幂等。

    site_presentation 为单例（id=1），保存当前生效的 preset/theme_tokens/
    navigation/home_blocks 与 config_revision。home_blocks 受支持类型限制在
    featured/recent/topic/category/continue，由应用层 pydantic schema 验证，
    不直接执行用户代码。每次发布写一条 site_presentation_revisions 历史快照，
    回退生成新 revision 而非覆盖历史，旧默认主题仍可恢复（enabled=False 即
    回退到默认区块顺序）。两套预设（software/tutorial）由应用层常量定义，
    切换无需改源码。
    """
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS site_presentation("
        "id INTEGER PRIMARY KEY,"
        "enabled BOOLEAN NOT NULL DEFAULT 0,"
        "preset VARCHAR(20) NOT NULL DEFAULT 'custom',"
        "theme_tokens_json TEXT NOT NULL DEFAULT '{}',"
        "navigation_json TEXT NOT NULL DEFAULT '[]',"
        "home_blocks_json TEXT NOT NULL DEFAULT '[]',"
        "config_revision INTEGER NOT NULL DEFAULT 1,"
        "updated_by VARCHAR(100) NOT NULL DEFAULT '',"
        "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        "CHECK (preset IN ('software', 'tutorial', 'custom')))"
    )
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS site_presentation_revisions("
        "revision_id INTEGER PRIMARY KEY,"
        "revision INTEGER NOT NULL,"
        "preset VARCHAR(20) NOT NULL DEFAULT 'custom',"
        "theme_tokens_json TEXT NOT NULL DEFAULT '{}',"
        "navigation_json TEXT NOT NULL DEFAULT '[]',"
        "home_blocks_json TEXT NOT NULL DEFAULT '[]',"
        "summary VARCHAR(200) NOT NULL DEFAULT '',"
        "created_by VARCHAR(100) NOT NULL DEFAULT '',"
        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_site_presentation_revisions_revision "
        "ON site_presentation_revisions (revision)"
    )


async def state_v12_to_v13_upgrade(conn: AsyncConnection) -> None:
    """Schema v12 -> v13: D2 合集条目强类型引用，幂等。

    为 collection_items 增加显式类型字段，使一条条目可引用原文件（resource）
    或 catalog 条目（catalog_entry），不再把两类 ID 塞进同一无类型字段：
    - item_type: 'resource' | 'catalog_entry'，默认 'resource' 保持旧文件引用兼容
    - catalog_entry_id: 当 item_type='catalog_entry' 时指向 catalog_entries.entry_id
      （跨表引用，不建 SQL 外键，与 catalog_locations.resource_id 同策略）
    - note: 该条目在合集内的说明文本
    保留 resource_id 列与现有 (collection_id, resource_id) 唯一约束，旧合集可读取。
    新增 (collection_id, catalog_entry_id) 唯一索引去重 catalog 条目（NULL 不参与）。
    """
    item_cols = await conn.exec_driver_sql("PRAGMA table_info(collection_items)")
    item_col_names = {row[1] for row in item_cols.fetchall()}
    if "item_type" not in item_col_names:
        await conn.exec_driver_sql(
            "ALTER TABLE collection_items ADD COLUMN item_type VARCHAR(20) NOT NULL DEFAULT 'resource'"
        )
    if "catalog_entry_id" not in item_col_names:
        await conn.exec_driver_sql(
            "ALTER TABLE collection_items ADD COLUMN catalog_entry_id VARCHAR(35)"
        )
    if "note" not in item_col_names:
        await conn.exec_driver_sql(
            "ALTER TABLE collection_items ADD COLUMN note TEXT NOT NULL DEFAULT ''"
        )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_collection_items_item_type ON collection_items (item_type)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_collection_items_catalog_entry_id ON collection_items (catalog_entry_id)"
    )
    await conn.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_collection_items_collection_catalog_entry "
        "ON collection_items (collection_id, catalog_entry_id)"
    )


async def state_v13_to_v14_upgrade(conn: AsyncConnection) -> None:
    """Schema v13 -> v14: D2 任务型专题扩展字段，幂等。

    为 collections 增加专题编排字段（复用现有 Collection 表，不引入新表）：
    - goal: 专题目标
    - audience: 目标对象
    - prerequisites: 准备条件
    - item_intro: 条目说明（合集级总说明，区别于每条 CollectionItem.note）
    旧合集保持可读：新列均有默认空串，向后兼容。
    """
    cols = await conn.exec_driver_sql("PRAGMA table_info(collections)")
    col_names = {row[1] for row in cols.fetchall()}
    for column, definition in (
        ("goal", "TEXT NOT NULL DEFAULT ''"),
        ("audience", "TEXT NOT NULL DEFAULT ''"),
        ("prerequisites", "TEXT NOT NULL DEFAULT ''"),
        ("item_intro", "TEXT NOT NULL DEFAULT ''"),
    ):
        if column not in col_names:
            await conn.exec_driver_sql(f"ALTER TABLE collections ADD COLUMN {column} {definition}")


async def state_v14_to_v15_upgrade(conn: AsyncConnection) -> None:
    """Schema v14 -> v15: collection_items.resource_id 改 nullable，幂等。

    D2 强类型引用允许 item_type='catalog_entry' 的条目 resource_id 为 NULL，
    但旧表建表时 resource_id 是 NOT NULL。SQLite 不能 ALTER COLUMN 改约束，
    需重建表。保留所有数据、索引与约束，仅放宽 resource_id 为 nullable。
    """
    cols = await conn.exec_driver_sql("PRAGMA table_info(collection_items)")
    col_names = {row[1] for row in cols.fetchall()}
    if "item_type" not in col_names:
        return
    resource_col = [row for row in await conn.exec_driver_sql("PRAGMA table_info(collection_items)") if row[1] == "resource_id"]
    if not resource_col or resource_col[0][3] == 0:
        return
    await conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
    await conn.exec_driver_sql(
        "CREATE TABLE collection_items_new("
        "id INTEGER PRIMARY KEY,"
        "collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,"
        "resource_id VARCHAR(64),"
        "item_type VARCHAR(20) NOT NULL DEFAULT 'resource',"
        "catalog_entry_id VARCHAR(35),"
        "note TEXT NOT NULL DEFAULT '',"
        "sort_order INTEGER NOT NULL DEFAULT 0,"
        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        "UNIQUE (collection_id, resource_id),"
        "UNIQUE (collection_id, catalog_entry_id),"
        "CHECK (item_type IN ('resource', 'catalog_entry')))"
    )
    await conn.exec_driver_sql(
        "INSERT INTO collection_items_new(id, collection_id, resource_id, item_type, catalog_entry_id, note, sort_order, created_at) "
        "SELECT id, collection_id, resource_id, item_type, catalog_entry_id, note, sort_order, created_at FROM collection_items"
    )
    await conn.exec_driver_sql("DROP TABLE collection_items")
    await conn.exec_driver_sql("ALTER TABLE collection_items_new RENAME TO collection_items")
    await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_collection_items_collection_id ON collection_items (collection_id)")
    await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_collection_items_resource_id ON collection_items (resource_id)")
    await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_collection_items_item_type ON collection_items (item_type)")
    await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_collection_items_catalog_entry_id ON collection_items (catalog_entry_id)")
    await conn.exec_driver_sql("PRAGMA foreign_keys=ON")




async def state_v15_to_v16_upgrade(conn: AsyncConnection) -> None:
    """Schema v15 -> v16: B2 建站向导状态表 + CatalogEntry.publicly_visible，幂等。

    新增 setup_wizard_state 单例表记录首次建站向导进度（connect/scope/preset/
    samples/brand/preview/publish 七步）。为 catalog_entries 增加 publicly_visible
    布尔字段，区分登录可见（默认 False）与公开可见（管理员显式公开），用于
    sitemap.xml 与公开 DTO。空库与已有 v15 库均可运行。
    """
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS setup_wizard_state("
        "id INTEGER PRIMARY KEY,"
        "current_step TEXT NOT NULL DEFAULT 'connect',"
        "completed_steps_json TEXT NOT NULL DEFAULT '[]',"
        "connect_done INTEGER NOT NULL DEFAULT 0,"
        "scope_done INTEGER NOT NULL DEFAULT 0,"
        "preset_done INTEGER NOT NULL DEFAULT 0,"
        "samples_done INTEGER NOT NULL DEFAULT 0,"
        "brand_done INTEGER NOT NULL DEFAULT 0,"
        "preview_done INTEGER NOT NULL DEFAULT 0,"
        "publish_done INTEGER NOT NULL DEFAULT 0,"
        "wizard_completed INTEGER NOT NULL DEFAULT 0,"
        "started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        "completed_at TEXT)"
    )
    catalog_cols = await conn.exec_driver_sql("PRAGMA table_info(catalog_entries)")
    if "publicly_visible" not in {row[1] for row in catalog_cols.fetchall()}:
        await conn.exec_driver_sql(
            "ALTER TABLE catalog_entries ADD COLUMN publicly_visible BOOLEAN NOT NULL DEFAULT 0"
        )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_entries_publicly_visible ON catalog_entries (publicly_visible)"
    )


async def state_v16_to_v17_upgrade(conn: AsyncConnection) -> None:
    """Schema v16 -> v17: M5 首页热门排序策略与全类型入口，幂等。

    为三张表增加首页编排相关字段：
    - site_settings.popular_strategy: 热门排序策略（recent/featured/manual），
      默认 'recent' 保持旧行为按 modified_at 排序，不再用 size 排序。
    - content_root_mappings.home_order: 首页排序权重，manual 策略下生效。
    - catalog_entries.featured: 手动精选标记，featured 策略下优先展示。

    所有新列均有默认值，旧 v16 行保持可读且语义向后兼容。
    """
    settings_cols = await conn.exec_driver_sql("PRAGMA table_info(site_settings)")
    settings_col_names = {row[1] for row in settings_cols.fetchall()}
    if "popular_strategy" not in settings_col_names:
        await conn.exec_driver_sql(
            "ALTER TABLE site_settings ADD COLUMN popular_strategy TEXT NOT NULL DEFAULT 'recent'"
        )

    root_cols = await conn.exec_driver_sql("PRAGMA table_info(content_root_mappings)")
    root_col_names = {row[1] for row in root_cols.fetchall()}
    if "home_order" not in root_col_names:
        await conn.exec_driver_sql(
            "ALTER TABLE content_root_mappings ADD COLUMN home_order INTEGER NOT NULL DEFAULT 0"
        )

    entry_cols = await conn.exec_driver_sql("PRAGMA table_info(catalog_entries)")
    entry_col_names = {row[1] for row in entry_cols.fetchall()}
    if "featured" not in entry_col_names:
        await conn.exec_driver_sql(
            "ALTER TABLE catalog_entries ADD COLUMN featured BOOLEAN NOT NULL DEFAULT 0"
        )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_catalog_entries_featured ON catalog_entries (featured)"
    )


async def state_v17_to_v18_upgrade(conn: AsyncConnection) -> None:
    """Schema v17 -> v18: M6 健康检查分级状态表 + health_check_enabled 开关，幂等。

    新增 health_check_state 表记录各组件（database/alist/storage）最近一次健康
    检查状态（healthy/degraded/unhealthy），用于 /api/ready 就绪探针持久化。
    为 system_settings 增加 health_check_enabled 列（默认 1），允许管理员关闭
    就绪探针的组件检查（存活探针 /api/health 不受影响）。空库与已有 v17 库均可运行。
    """
    settings_cols = await conn.exec_driver_sql("PRAGMA table_info(system_settings)")
    if "health_check_enabled" not in {row[1] for row in settings_cols.fetchall()}:
        await conn.exec_driver_sql(
            "ALTER TABLE system_settings ADD COLUMN health_check_enabled BOOLEAN NOT NULL DEFAULT 1"
        )
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS health_check_state("
        "id INTEGER PRIMARY KEY,"
        "component TEXT NOT NULL,"
        "status TEXT NOT NULL,"
        "last_check_at TEXT NOT NULL,"
        "last_error TEXT,"
        "UNIQUE(component))"
    )


async def state_v18_to_v19_upgrade(conn: AsyncConnection) -> None:
    """Schema v18 -> v19: A4 内容质量待办队列，幂等。

    新增四张表：
    - quality_todos: 质量待办项，带 (todo_type, target_type, target_id) WHERE status='open' 的唯一索引
    - quality_detection_runs: 检测运行记录，预算控制与幂等
    - search_query_logs: 搜索查询日志，无结果查询聚合
    - content_feedback: 用户内容反馈，提交时自动创建 quality_todo
    空库与已有 v18 库均可运行。
    """
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS quality_todos("
        "todo_id TEXT PRIMARY KEY,"
        "todo_type TEXT NOT NULL,"
        "target_type TEXT NOT NULL,"
        "target_id TEXT NOT NULL,"
        "severity TEXT NOT NULL DEFAULT 'medium',"
        "title TEXT NOT NULL,"
        "detail_json TEXT NOT NULL DEFAULT '{}',"
        "status TEXT NOT NULL DEFAULT 'open',"
        "source TEXT NOT NULL DEFAULT 'auto_detection',"
        "detection_run_id TEXT,"
        "dismissed_by TEXT NOT NULL DEFAULT '',"
        "dismissed_at TEXT,"
        "dismiss_reason TEXT NOT NULL DEFAULT '',"
        "resolved_at TEXT,"
        "created_at TEXT NOT NULL,"
        "updated_at TEXT NOT NULL,"
        "CHECK(todo_type IN ('missing_description','stale_location','old_version_review',"
        "'source_conflict','suspected_duplicate','no_result_query')),"
        "CHECK(status IN ('open','dismissed','resolved','wontfix')),"
        "CHECK(severity IN ('low','medium','high')),"
        "CHECK(source IN ('auto_detection','user_feedback')))"
    )
    await conn.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_quality_todos_open_dedup "
        "ON quality_todos(todo_type, target_type, target_id) WHERE status = 'open'"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_quality_todos_type_status "
        "ON quality_todos(todo_type, status)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_quality_todos_target_id ON quality_todos(target_id)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_quality_todos_run_id ON quality_todos(detection_run_id)"
    )
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS quality_detection_runs("
        "run_id TEXT PRIMARY KEY,"
        "started_at TEXT NOT NULL,"
        "completed_at TEXT,"
        "items_found INTEGER NOT NULL DEFAULT 0,"
        "items_deduplicated INTEGER NOT NULL DEFAULT 0,"
        "budget_ms INTEGER NOT NULL DEFAULT 5000,"
        "actual_ms INTEGER,"
        "status TEXT NOT NULL DEFAULT 'running',"
        "detail_json TEXT NOT NULL DEFAULT '{}',"
        "CHECK(status IN ('running','completed','timeout')))"
    )
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS search_query_logs("
        "log_id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "query TEXT NOT NULL,"
        "result_count INTEGER NOT NULL DEFAULT 0,"
        "user_id INTEGER,"
        "content_type_filter TEXT,"
        "platform_filter TEXT,"
        "created_at TEXT NOT NULL)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_search_query_logs_query ON search_query_logs(query)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_search_query_logs_user ON search_query_logs(user_id)"
    )
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS content_feedback("
        "feedback_id TEXT PRIMARY KEY,"
        "user_id INTEGER NOT NULL,"
        "target_type TEXT NOT NULL,"
        "target_id TEXT NOT NULL,"
        "feedback_kind TEXT NOT NULL,"
        "description TEXT NOT NULL,"
        "status TEXT NOT NULL DEFAULT 'pending',"
        "admin_note TEXT NOT NULL DEFAULT '',"
        "reviewed_by TEXT NOT NULL DEFAULT '',"
        "reviewed_at TEXT,"
        "todo_id TEXT,"
        "created_at TEXT NOT NULL,"
        "updated_at TEXT NOT NULL,"
        "CHECK(target_type IN ('entry','asset','location')),"
        "CHECK(feedback_kind IN ('broken_link','wrong_info','missing_content','other')),"
        "CHECK(status IN ('pending','reviewed','resolved')))"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_content_feedback_status ON content_feedback(status)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_content_feedback_user ON content_feedback(user_id)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_content_feedback_target ON content_feedback(target_id)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_content_feedback_todo ON content_feedback(todo_id)"
    )


async def state_v19_to_v20_upgrade(conn: AsyncConnection) -> None:
    """Schema v19 -> v20: A3 可选 AI 内容补全，幂等。

    新增三张表：
    - ai_provider_configs: AI 提供方配置（provider类型、endpoint、model、预算、开关）
    - ai_generation_drafts: AI 生成草稿（简介/标签/别名/用途，带幂等唯一索引）
    - ai_budget_usage: 每日预算用量（按 config_id + date 唯一）
    空库与已有 v19 库均可运行。
    """
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS ai_provider_configs("
        "config_id TEXT PRIMARY KEY,"
        "provider_type TEXT NOT NULL,"
        "display_name TEXT NOT NULL,"
        "endpoint_url TEXT NOT NULL DEFAULT '',"
        "api_key_encrypted TEXT NOT NULL DEFAULT '',"
        "model_name TEXT NOT NULL DEFAULT '',"
        "enabled BOOLEAN NOT NULL DEFAULT 0,"
        "daily_budget_tokens INTEGER NOT NULL DEFAULT 100000,"
        "daily_budget_requests INTEGER NOT NULL DEFAULT 100,"
        "timeout_seconds INTEGER NOT NULL DEFAULT 30,"
        "max_retries INTEGER NOT NULL DEFAULT 2,"
        "created_at TEXT NOT NULL,"
        "updated_at TEXT NOT NULL,"
        "CHECK(provider_type IN ('local_ollama','openai_compatible','custom')))"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_ai_provider_configs_enabled ON ai_provider_configs(enabled)"
    )
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS ai_generation_drafts("
        "draft_id TEXT PRIMARY KEY,"
        "target_type TEXT NOT NULL,"
        "target_id TEXT NOT NULL,"
        "field_type TEXT NOT NULL,"
        "provider_type TEXT NOT NULL,"
        "model_name TEXT NOT NULL DEFAULT '',"
        "prompt_template_version TEXT NOT NULL DEFAULT '1.0.0',"
        "source_pointers_json TEXT NOT NULL DEFAULT '[]',"
        "generated_content TEXT NOT NULL DEFAULT '',"
        "candidate_status TEXT NOT NULL DEFAULT 'pending',"
        "input_material_hash TEXT NOT NULL,"
        "config_id TEXT,"
        "tokens_used INTEGER NOT NULL DEFAULT 0,"
        "elapsed_ms INTEGER NOT NULL DEFAULT 0,"
        "error_message TEXT NOT NULL DEFAULT '',"
        "reviewed_by TEXT NOT NULL DEFAULT '',"
        "reviewed_at TEXT,"
        "created_at TEXT NOT NULL,"
        "updated_at TEXT NOT NULL,"
        "CHECK(target_type = 'entry'),"
        "CHECK(field_type IN ('summary','tags','aliases','usage_note')),"
        "CHECK(candidate_status IN ('pending','accepted','rejected','modified')))"
    )
    await conn.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_ai_drafts_pending_dedup "
        "ON ai_generation_drafts(target_type, target_id, field_type, input_material_hash) "
        "WHERE candidate_status = 'pending'"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_ai_drafts_target_field "
        "ON ai_generation_drafts(target_id, field_type)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_ai_drafts_status ON ai_generation_drafts(candidate_status)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_ai_drafts_config ON ai_generation_drafts(config_id)"
    )
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS ai_budget_usage("
        "usage_id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "config_id TEXT NOT NULL,"
        "date TEXT NOT NULL,"
        "tokens_used INTEGER NOT NULL DEFAULT 0,"
        "requests_used INTEGER NOT NULL DEFAULT 0,"
        "created_at TEXT NOT NULL,"
        "updated_at TEXT NOT NULL,"
        "UNIQUE(config_id, date))"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_ai_budget_usage_config ON ai_budget_usage(config_id)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_ai_budget_usage_date ON ai_budget_usage(date)"
    )


async def state_v20_to_v21_upgrade(conn: AsyncConnection) -> None:
    """G2 指标采集：metric_events、metric_baselines、metric_summaries。"""
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS metric_events("
        "id TEXT PRIMARY KEY,"
        "event_type TEXT NOT NULL,"
        "event_data TEXT,"
        "user_id TEXT,"
        "created_at TEXT NOT NULL)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_metric_events_type ON metric_events(event_type)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_metric_events_user ON metric_events(user_id)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_metric_events_created ON metric_events(created_at)"
    )
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS metric_baselines("
        "id TEXT PRIMARY KEY,"
        "label TEXT NOT NULL,"
        "period_start TEXT NOT NULL,"
        "period_end TEXT NOT NULL,"
        "summary_json TEXT NOT NULL DEFAULT '{}',"
        "created_at TEXT NOT NULL)"
    )
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS metric_summaries("
        "id TEXT PRIMARY KEY,"
        "period_start TEXT NOT NULL,"
        "period_end TEXT NOT NULL,"
        "metric_type TEXT NOT NULL,"
        "value REAL NOT NULL DEFAULT 0,"
        "sample_count INTEGER NOT NULL DEFAULT 0,"
        "created_at TEXT NOT NULL)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_metric_summaries_period_start ON metric_summaries(period_start)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_metric_summaries_period_end ON metric_summaries(period_end)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_metric_summaries_type ON metric_summaries(metric_type)"
    )


async def state_v21_to_v22_upgrade(conn: AsyncConnection) -> None:
    """T1 团队角色：users.role + operation_logs.principal/actor_user_id。"""
    user_cols = await conn.exec_driver_sql("PRAGMA table_info(users)")
    if not any(row[1] == "role" for row in user_cols):
        await conn.exec_driver_sql(
            "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'viewer'"
        )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_users_role ON users(role)"
    )
    op_cols = await conn.exec_driver_sql("PRAGMA table_info(operation_logs)")
    if not any(row[1] == "principal" for row in op_cols):
        await conn.exec_driver_sql(
            "ALTER TABLE operation_logs ADD COLUMN principal TEXT NOT NULL DEFAULT ''"
        )
    if not any(row[1] == "actor_user_id" for row in op_cols):
        await conn.exec_driver_sql(
            "ALTER TABLE operation_logs ADD COLUMN actor_user_id INTEGER"
        )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_operation_logs_actor ON operation_logs(actor_user_id)"
    )


async def state_v22_to_v23_upgrade(conn: AsyncConnection) -> None:
    """T2 交付包：delivery_packages + delivery_package_items。"""
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS delivery_packages("
        "package_id TEXT PRIMARY KEY,"
        "name TEXT NOT NULL,"
        "project_note TEXT NOT NULL DEFAULT '',"
        "revision INTEGER NOT NULL DEFAULT 1,"
        "creator_user_id INTEGER,"
        "access_token TEXT NOT NULL,"
        "code_hash TEXT,"
        "expires_at TEXT,"
        "status TEXT NOT NULL DEFAULT 'draft',"
        "published_at TEXT,"
        "cancelled_at TEXT,"
        "created_at TEXT NOT NULL,"
        "updated_at TEXT NOT NULL)"
    )
    await conn.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_delivery_packages_token ON delivery_packages(access_token)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_delivery_packages_status ON delivery_packages(status)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_delivery_packages_creator ON delivery_packages(creator_user_id)"
    )
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS delivery_package_items("
        "item_id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "package_id TEXT NOT NULL,"
        "asset_id TEXT,"
        "resource_id TEXT,"
        "display_name TEXT NOT NULL DEFAULT '',"
        "bound_checksum TEXT,"
        "bound_checksum_algorithm TEXT,"
        "bound_size INTEGER,"
        "sort_order INTEGER NOT NULL DEFAULT 0,"
        "note TEXT NOT NULL DEFAULT '',"
        "created_at TEXT NOT NULL,"
        "UNIQUE(package_id, asset_id),"
        "UNIQUE(package_id, resource_id),"
        "FOREIGN KEY(package_id) REFERENCES delivery_packages(package_id) ON DELETE CASCADE)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_delivery_items_package ON delivery_package_items(package_id)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_delivery_items_asset ON delivery_package_items(asset_id)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_delivery_items_resource ON delivery_package_items(resource_id)"
    )


async def state_v23_to_v24_upgrade(conn: AsyncConnection) -> None:
    """X2 开放生态：api_tokens + webhook_endpoints + webhook_deliveries。"""
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS api_tokens("
        "token_id TEXT PRIMARY KEY,"
        "token_hash TEXT NOT NULL,"
        "label TEXT NOT NULL DEFAULT '',"
        "scopes TEXT NOT NULL DEFAULT '[]',"
        "status TEXT NOT NULL DEFAULT 'active',"
        "created_by TEXT NOT NULL DEFAULT '',"
        "expires_at TEXT,"
        "last_used_at TEXT,"
        "created_at TEXT NOT NULL,"
        "updated_at TEXT NOT NULL)"
    )
    await conn.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_api_tokens_hash ON api_tokens(token_hash)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_api_tokens_status ON api_tokens(status)"
    )
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS webhook_endpoints("
        "endpoint_id TEXT PRIMARY KEY,"
        "url TEXT NOT NULL,"
        "secret TEXT NOT NULL DEFAULT '',"
        "event_types TEXT NOT NULL DEFAULT '[]',"
        "status TEXT NOT NULL DEFAULT 'active',"
        "max_retries INTEGER NOT NULL DEFAULT 3,"
        "created_at TEXT NOT NULL,"
        "updated_at TEXT NOT NULL)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_webhook_endpoints_status ON webhook_endpoints(status)"
    )
    await conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS webhook_deliveries("
        "delivery_id TEXT PRIMARY KEY,"
        "endpoint_id TEXT NOT NULL,"
        "event_id TEXT NOT NULL,"
        "event_type TEXT NOT NULL,"
        "payload TEXT NOT NULL DEFAULT '{}',"
        "status TEXT NOT NULL DEFAULT 'pending',"
        "attempts INTEGER NOT NULL DEFAULT 0,"
        "response_code INTEGER,"
        "response_body TEXT,"
        "next_retry_at TEXT,"
        "created_at TEXT NOT NULL,"
        "updated_at TEXT NOT NULL,"
        "FOREIGN KEY(endpoint_id) REFERENCES webhook_endpoints(endpoint_id) ON DELETE CASCADE)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_webhook_deliveries_endpoint ON webhook_deliveries(endpoint_id)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_webhook_deliveries_event ON webhook_deliveries(event_id)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_webhook_deliveries_status ON webhook_deliveries(status)"
    )


STATE_MIGRATIONS: list[Migration] = [
    Migration(id="state_v1_to_v2", from_version=1, to_version=2, upgrade=state_v1_to_v2_upgrade),
    Migration(id="state_v2_to_v3", from_version=2, to_version=3, upgrade=state_v2_to_v3_upgrade),
    Migration(id="state_v3_to_v4", from_version=3, to_version=4, upgrade=state_v3_to_v4_upgrade),
    Migration(id="state_v4_to_v5", from_version=4, to_version=5, upgrade=state_v4_to_v5_upgrade),
    Migration(id="state_v5_to_v6", from_version=5, to_version=6, upgrade=state_v5_to_v6_upgrade),
    Migration(id="state_v6_to_v7", from_version=6, to_version=7, upgrade=state_v6_to_v7_upgrade),
    Migration(id="state_v7_to_v8", from_version=7, to_version=8, upgrade=state_v7_to_v8_upgrade),
    Migration(id="state_v8_to_v9", from_version=8, to_version=9, upgrade=state_v8_to_v9_upgrade),
    Migration(id="state_v9_to_v10", from_version=9, to_version=10, upgrade=state_v9_to_v10_upgrade),
    Migration(id="state_v10_to_v11", from_version=10, to_version=11, upgrade=state_v10_to_v11_upgrade),
    Migration(id="state_v11_to_v12", from_version=11, to_version=12, upgrade=state_v11_to_v12_upgrade),
    Migration(id="state_v12_to_v13", from_version=12, to_version=13, upgrade=state_v12_to_v13_upgrade),
    Migration(id="state_v13_to_v14", from_version=13, to_version=14, upgrade=state_v13_to_v14_upgrade),
    Migration(id="state_v14_to_v15", from_version=14, to_version=15, upgrade=state_v14_to_v15_upgrade),
    Migration(id="state_v15_to_v16", from_version=15, to_version=16, upgrade=state_v15_to_v16_upgrade),
    Migration(id="state_v16_to_v17", from_version=16, to_version=17, upgrade=state_v16_to_v17_upgrade),
    Migration(id="state_v17_to_v18", from_version=17, to_version=18, upgrade=state_v17_to_v18_upgrade),
    Migration(id="state_v18_to_v19", from_version=18, to_version=19, upgrade=state_v18_to_v19_upgrade),
    Migration(id="state_v19_to_v20", from_version=19, to_version=20, upgrade=state_v19_to_v20_upgrade),
    Migration(id="state_v20_to_v21", from_version=20, to_version=21, upgrade=state_v20_to_v21_upgrade),
    Migration(id="state_v21_to_v22", from_version=21, to_version=22, upgrade=state_v21_to_v22_upgrade),
    Migration(id="state_v22_to_v23", from_version=22, to_version=23, upgrade=state_v22_to_v23_upgrade),
    Migration(id="state_v23_to_v24", from_version=23, to_version=24, upgrade=state_v23_to_v24_upgrade),
]

