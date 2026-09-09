-- CloudSite 0.5.1 state.db reviewable fixture
-- Provenance: schema and representative rows derived from commit 4d69cb3
--   (feat: release CloudSite 0.5.1 user library and native video)
--   apps/api/cloudsite/models.py @ 4d69cb3
--   apps/api/cloudsite/database.py @ 4d69cb3 (init_databases state branch)
-- Generation: hand-written from the ORM column definitions at 4d69cb3.
--   No production ORM metadata is used at runtime to build this schema.
-- Safety: all values are deterministic placeholders. No real user data,
--   no real password hashes, no real ciphertext, no real tokens.
-- Scope: state.db tables only (StateBase descendants at 4d69cb3).
--   Index.db tables (folders/resources/sync_*) are out of scope.

PRAGMA foreign_keys = ON;

-- ----------------------------------------------------------------------
-- Schema (state.db @ 4d69cb3)
-- ----------------------------------------------------------------------

CREATE TABLE alist_connections (
    id INTEGER NOT NULL PRIMARY KEY,
    base_url VARCHAR(500) NOT NULL,
    base_path VARCHAR(1000) NOT NULL,
    username VARCHAR(200) NOT NULL,
    password_ciphertext TEXT NOT NULL,
    remember_credentials BOOLEAN NOT NULL,
    enabled BOOLEAN NOT NULL,
    last_test_status VARCHAR(40) NOT NULL,
    last_test_message TEXT NOT NULL,
    last_test_at DATETIME,
    provider_type VARCHAR(40) NOT NULL,
    provider_capability_version INTEGER NOT NULL,
    provider_capabilities_json TEXT NOT NULL,
    capabilities_checked_at DATETIME,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);

CREATE TABLE site_settings (
    id INTEGER NOT NULL PRIMARY KEY,
    site_name VARCHAR(100) NOT NULL,
    home_title VARCHAR(200) NOT NULL,
    description VARCHAR(500) NOT NULL,
    hero_subtitle VARCHAR(200) NOT NULL,
    footer_text VARCHAR(300) NOT NULL,
    submission_email VARCHAR(200) NOT NULL,
    github_url VARCHAR(300) NOT NULL,
    registration_enabled BOOLEAN NOT NULL,
    default_share_duration VARCHAR(20) NOT NULL,
    share_image_name VARCHAR(255) NOT NULL,
    recent_limit INTEGER NOT NULL,
    popular_limit INTEGER NOT NULL,
    collection_limit INTEGER NOT NULL,
    updated_at DATETIME NOT NULL
);

CREATE TABLE system_settings (
    key VARCHAR(100) NOT NULL PRIMARY KEY,
    value TEXT NOT NULL,
    value_type VARCHAR(20) NOT NULL,
    updated_at DATETIME NOT NULL
);

CREATE TABLE content_root_mappings (
    id INTEGER NOT NULL PRIMARY KEY,
    content_type VARCHAR(40) NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    alist_path VARCHAR(1000) NOT NULL UNIQUE,
    enabled BOOLEAN NOT NULL,
    sort_order INTEGER NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);

CREATE TABLE download_events (
    id INTEGER NOT NULL PRIMARY KEY,
    resource_id VARCHAR(64) NOT NULL,
    result VARCHAR(20) NOT NULL,
    error_code VARCHAR(20),
    duration_ms INTEGER NOT NULL,
    source VARCHAR(20) NOT NULL,
    created_at DATETIME NOT NULL
);

CREATE TABLE download_diagnostics (
    id INTEGER NOT NULL PRIMARY KEY,
    resource_id VARCHAR(64) NOT NULL,
    status VARCHAR(20) NOT NULL,
    failed_step VARCHAR(40) NOT NULL,
    error_code VARCHAR(20),
    message VARCHAR(500) NOT NULL,
    duration_ms INTEGER NOT NULL,
    target_host VARCHAR(300) NOT NULL,
    created_at DATETIME NOT NULL
);

CREATE TABLE operation_logs (
    id INTEGER NOT NULL PRIMARY KEY,
    level VARCHAR(20) NOT NULL,
    module VARCHAR(50) NOT NULL,
    action VARCHAR(80) NOT NULL,
    message TEXT NOT NULL,
    created_at DATETIME NOT NULL
);

CREATE TABLE collections (
    id INTEGER NOT NULL PRIMARY KEY,
    name VARCHAR(160) NOT NULL,
    description TEXT NOT NULL,
    cover TEXT NOT NULL,
    status VARCHAR(20) NOT NULL,
    visible_on_home BOOLEAN NOT NULL,
    sort_order INTEGER NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);

CREATE TABLE collection_items (
    id INTEGER NOT NULL PRIMARY KEY,
    collection_id INTEGER NOT NULL REFERENCES collections (id) ON DELETE CASCADE,
    resource_id VARCHAR(64) NOT NULL,
    sort_order INTEGER NOT NULL,
    created_at DATETIME NOT NULL,
    UNIQUE (collection_id, resource_id)
);

CREATE TABLE shares (
    token VARCHAR(64) NOT NULL PRIMARY KEY,
    creator_user_id INTEGER REFERENCES users (id) ON DELETE SET NULL,
    object_type VARCHAR(20) NOT NULL,
    object_id VARCHAR(64) NOT NULL,
    title VARCHAR(200) NOT NULL,
    enabled BOOLEAN NOT NULL,
    access_mode VARCHAR(20) NOT NULL,
    code_hash VARCHAR(64),
    code_version INTEGER NOT NULL,
    expires_at DATETIME,
    cancelled_at DATETIME,
    cancel_reason VARCHAR(30),
    access_count INTEGER NOT NULL,
    view_count INTEGER NOT NULL,
    download_count INTEGER NOT NULL,
    last_accessed_at DATETIME,
    last_downloaded_at DATETIME,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);

CREATE TABLE share_verify_attempts (
    id INTEGER NOT NULL PRIMARY KEY,
    share_token VARCHAR(64) NOT NULL,
    ip_hash VARCHAR(64) NOT NULL,
    fail_count INTEGER NOT NULL,
    window_started_at DATETIME NOT NULL,
    challenge_required_until DATETIME,
    updated_at DATETIME NOT NULL,
    UNIQUE (share_token, ip_hash)
);

CREATE TABLE users (
    id INTEGER NOT NULL PRIMARY KEY,
    username VARCHAR(32) NOT NULL,
    username_normalized VARCHAR(32) NOT NULL,
    password_hash TEXT NOT NULL,
    status VARCHAR(20) NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    last_login_at DATETIME,
    password_changed_at DATETIME,
    disabled_at DATETIME,
    deleted_at DATETIME,
    created_by_admin BOOLEAN NOT NULL
);

CREATE TABLE user_sessions (
    id INTEGER NOT NULL PRIMARY KEY,
    session_token_hash VARCHAR(64) NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    created_at DATETIME NOT NULL,
    expires_at DATETIME NOT NULL,
    last_seen_at DATETIME NOT NULL,
    revoked_at DATETIME,
    created_ip_hash VARCHAR(64),
    user_agent_hash VARCHAR(64)
);

CREATE TABLE user_favorites (
    id INTEGER NOT NULL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    resource_id VARCHAR(64) NOT NULL,
    created_at DATETIME NOT NULL,
    UNIQUE (user_id, resource_id)
);

CREATE TABLE user_resource_history (
    id INTEGER NOT NULL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    resource_id VARCHAR(64) NOT NULL,
    first_viewed_at DATETIME NOT NULL,
    last_viewed_at DATETIME NOT NULL,
    view_count INTEGER NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    UNIQUE (user_id, resource_id)
);

CREATE TABLE user_playback_progress (
    id INTEGER NOT NULL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    resource_id VARCHAR(64) NOT NULL,
    position_seconds INTEGER NOT NULL,
    duration_seconds INTEGER NOT NULL,
    completed BOOLEAN NOT NULL,
    last_played_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    UNIQUE (user_id, resource_id)
);

CREATE TABLE download_rate_limits (
    id INTEGER NOT NULL PRIMARY KEY,
    ip_key VARCHAR(64) NOT NULL,
    recent_hits_json TEXT NOT NULL,
    blocked_until DATETIME,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);

CREATE TABLE resource_identities (
    resource_id VARCHAR(64) NOT NULL PRIMARY KEY,
    current_path VARCHAR(1500),
    root_mapping_id INTEGER,
    status VARCHAR(30) NOT NULL,
    first_seen_at DATETIME NOT NULL,
    last_seen_at DATETIME NOT NULL,
    last_name VARCHAR(500) NOT NULL,
    last_extension VARCHAR(40) NOT NULL,
    last_mime_type VARCHAR(200) NOT NULL,
    last_size BIGINT NOT NULL,
    last_modified_at DATETIME,
    provider_object_id VARCHAR(500),
    content_hash VARCHAR(200),
    identity_fingerprint VARCHAR(64),
    fingerprint_version INTEGER NOT NULL,
    created_from VARCHAR(30) NOT NULL,
    updated_at DATETIME NOT NULL
);

CREATE TABLE resource_identity_history (
    id INTEGER NOT NULL PRIMARY KEY,
    resource_id VARCHAR(64) NOT NULL REFERENCES resource_identities (resource_id) ON DELETE RESTRICT,
    path VARCHAR(1500) NOT NULL,
    event_type VARCHAR(30) NOT NULL,
    first_observed_at DATETIME NOT NULL,
    last_observed_at DATETIME NOT NULL,
    from_path VARCHAR(1500),
    to_path VARCHAR(1500),
    cycle_id INTEGER,
    created_at DATETIME NOT NULL
);

-- ----------------------------------------------------------------------
-- Indexes (declared at 4d69cb3 via mapped_column index=True / __table_args__)
-- ----------------------------------------------------------------------

CREATE INDEX ix_content_root_mappings_content_type ON content_root_mappings (content_type);
CREATE INDEX ix_download_events_resource_id ON download_events (resource_id);
CREATE INDEX ix_download_diagnostics_resource_id ON download_diagnostics (resource_id);
CREATE INDEX ix_download_diagnostics_status ON download_diagnostics (status);
CREATE INDEX ix_collections_name ON collections (name);
CREATE INDEX ix_collections_status ON collections (status);
CREATE INDEX ix_collections_visible_on_home ON collections (visible_on_home);
CREATE INDEX ix_collection_items_collection_id ON collection_items (collection_id);
CREATE INDEX ix_collection_items_resource_id ON collection_items (resource_id);
CREATE INDEX ix_shares_creator_user_id ON shares (creator_user_id);
CREATE INDEX ix_shares_object_type ON shares (object_type);
CREATE INDEX ix_shares_object_id ON shares (object_id);
CREATE INDEX ix_shares_enabled ON shares (enabled);
CREATE INDEX ix_shares_access_mode ON shares (access_mode);
CREATE INDEX ix_share_verify_attempts_share_token ON share_verify_attempts (share_token);
CREATE INDEX ix_share_verify_attempts_ip_hash ON share_verify_attempts (ip_hash);
CREATE INDEX ix_share_verify_attempts_challenge_required_until ON share_verify_attempts (challenge_required_until);
CREATE UNIQUE INDEX ix_users_username_normalized ON users (username_normalized);
CREATE INDEX ix_users_status ON users (status);
CREATE INDEX ix_users_disabled_at ON users (disabled_at);
CREATE INDEX ix_users_deleted_at ON users (deleted_at);
CREATE UNIQUE INDEX ix_user_sessions_session_token_hash ON user_sessions (session_token_hash);
CREATE INDEX ix_user_sessions_user_id ON user_sessions (user_id);
CREATE INDEX ix_user_sessions_expires_at ON user_sessions (expires_at);
CREATE INDEX ix_user_sessions_revoked_at ON user_sessions (revoked_at);
CREATE INDEX ix_user_favorites_user_id ON user_favorites (user_id);
CREATE INDEX ix_user_favorites_resource_id ON user_favorites (resource_id);
CREATE INDEX ix_user_favorites_user_created_at ON user_favorites (user_id, created_at);
CREATE INDEX ix_user_resource_history_user_id ON user_resource_history (user_id);
CREATE INDEX ix_user_resource_history_resource_id ON user_resource_history (resource_id);
CREATE INDEX ix_user_resource_history_last_viewed_at ON user_resource_history (last_viewed_at);
CREATE INDEX ix_user_resource_history_user_last_viewed_at ON user_resource_history (user_id, last_viewed_at);
CREATE INDEX ix_user_playback_progress_user_id ON user_playback_progress (user_id);
CREATE INDEX ix_user_playback_progress_resource_id ON user_playback_progress (resource_id);
CREATE INDEX ix_user_playback_progress_completed ON user_playback_progress (completed);
CREATE INDEX ix_user_playback_progress_last_played_at ON user_playback_progress (last_played_at);
CREATE INDEX ix_user_playback_progress_user_last_played_at ON user_playback_progress (user_id, last_played_at);
CREATE INDEX ix_user_playback_progress_user_completed ON user_playback_progress (user_id, completed);
CREATE UNIQUE INDEX ix_download_rate_limits_ip_key ON download_rate_limits (ip_key);
CREATE INDEX ix_download_rate_limits_blocked_until ON download_rate_limits (blocked_until);
CREATE INDEX ix_download_rate_limits_updated_at ON download_rate_limits (updated_at);
CREATE INDEX ix_resource_identities_current_path ON resource_identities (current_path);
CREATE INDEX ix_resource_identities_root_mapping_id ON resource_identities (root_mapping_id);
CREATE INDEX ix_resource_identities_status ON resource_identities (status);
CREATE INDEX ix_resource_identities_provider_object_id ON resource_identities (provider_object_id);
CREATE INDEX ix_resource_identities_content_hash ON resource_identities (content_hash);
CREATE INDEX ix_resource_identities_identity_fingerprint ON resource_identities (identity_fingerprint);
CREATE INDEX ix_resource_identity_history_resource_id ON resource_identity_history (resource_id);
CREATE INDEX ix_resource_identity_history_path ON resource_identity_history (path);
CREATE INDEX ix_resource_identity_history_event_type ON resource_identity_history (event_type);
CREATE INDEX ix_resource_identity_history_cycle_id ON resource_identity_history (cycle_id);

-- ----------------------------------------------------------------------
-- Representative rows (deterministic placeholders only)
-- ----------------------------------------------------------------------

-- AList connection (business entity: AList connection)
INSERT INTO alist_connections (
    id, base_url, base_path, username, password_ciphertext,
    remember_credentials, enabled, last_test_status, last_test_message,
    last_test_at, provider_type, provider_capability_version,
    provider_capabilities_json, capabilities_checked_at,
    created_at, updated_at
) VALUES (
    1,
    'https://alist.fixture.example',
    '/',
    'fixture-admin',
    'fixture-ciphertext-not-a-real-secret',
    1, 1, 'ok', '',
    '2026-09-04 12:00:00.000000',
    'generic_alist', 1,
    '{}', '2026-09-04 12:00:00.000000',
    '2026-09-04 12:00:00.000000',
    '2026-09-04 12:00:00.000000'
);

-- Site settings (required state identity table)
INSERT INTO site_settings (
    id, site_name, home_title, description, hero_subtitle, footer_text,
    submission_email, github_url, registration_enabled,
    default_share_duration, share_image_name,
    recent_limit, popular_limit, collection_limit, updated_at
) VALUES (
    1,
    'CloudSite Fixture',
    'Fixture home title',
    'Fixture description for 0.5.1 state',
    'Fixture hero subtitle',
    'Fixture footer text',
    'fixture@example.invalid',
    'https://github.com/example/cloudsite-fixture',
    1,
    '24h',
    '',
    6, 6, 4,
    '2026-09-04 12:00:00.000000'
);

-- System settings (required state identity table)
INSERT INTO system_settings (key, value, value_type, updated_at) VALUES
    ('fixture.key', 'fixture-value', 'string', '2026-09-04 12:00:00.000000'),
    ('schema_version', '0.5.1', 'string', '2026-09-04 12:00:00.000000');

-- ContentRoot mappings (business entity: ContentRoot)
INSERT INTO content_root_mappings (
    id, content_type, display_name, alist_path, enabled, sort_order,
    created_at, updated_at
) VALUES
    (1, 'software', 'Software', '/software', 1, 0,
     '2026-09-04 12:00:00.000000', '2026-09-04 12:00:00.000000'),
    (2, 'video', 'Videos', '/videos', 1, 1,
     '2026-09-04 12:00:00.000000', '2026-09-04 12:00:00.000000');

-- Users (business entity: user)
INSERT INTO users (
    id, username, username_normalized, password_hash, status,
    created_at, updated_at, last_login_at, password_changed_at,
    disabled_at, deleted_at, created_by_admin
) VALUES
    (1, 'fixture-user', 'fixture-user', 'fixture-hash-not-a-real-password',
     'active',
     '2026-09-04 12:00:00.000000', '2026-09-04 12:00:00.000000',
     '2026-09-04 12:30:00.000000', '2026-09-04 12:00:00.000000',
     NULL, NULL, 0),
    (2, 'fixture-admin', 'fixture-admin', 'fixture-hash-not-a-real-password',
     'active',
     '2026-09-04 12:00:00.000000', '2026-09-04 12:00:00.000000',
     '2026-09-04 12:30:00.000000', '2026-09-04 12:00:00.000000',
     NULL, NULL, 1);

-- User sessions (representative, references users)
INSERT INTO user_sessions (
    id, session_token_hash, user_id, created_at, expires_at, last_seen_at,
    revoked_at, created_ip_hash, user_agent_hash
) VALUES
    (1, 'fixture-session-hash-user-0001', 1,
     '2026-09-04 12:30:00.000000', '2026-09-05 12:30:00.000000',
     '2026-09-04 13:00:00.000000', NULL,
     'fixture-ip-hash-0001', 'fixture-ua-hash-0001');

-- Resource identities (business entity: resource identity)
-- Stable resource IDs are the cross-version anchor for user data.
INSERT INTO resource_identities (
    resource_id, current_path, root_mapping_id, status,
    first_seen_at, last_seen_at,
    last_name, last_extension, last_mime_type, last_size,
    last_modified_at, provider_object_id, content_hash,
    identity_fingerprint, fingerprint_version, created_from, updated_at
) VALUES
    ('fixture-resource-001', '/software/cloudsite-0.5.1.zip', 1, 'active',
     '2026-09-04 12:00:00.000000', '2026-09-04 12:00:00.000000',
     'cloudsite-0.5.1', 'zip', 'application/zip', 1024,
     '2026-09-04 11:00:00.000000', 'fixture-provider-object-001',
     'fixture-content-hash-001', 'fixture-fingerprint-001', 1,
     'new_resource', '2026-09-04 12:00:00.000000'),
    ('fixture-resource-002', '/videos/demo.mp4', 2, 'active',
     '2026-09-04 12:00:00.000000', '2026-09-04 12:00:00.000000',
     'demo', 'mp4', 'video/mp4', 2048,
     '2026-09-04 11:00:00.000000', 'fixture-provider-object-002',
     'fixture-content-hash-002', 'fixture-fingerprint-002', 1,
     'new_resource', '2026-09-04 12:00:00.000000');

-- Resource identity history (representative, references resource_identities)
INSERT INTO resource_identity_history (
    id, resource_id, path, event_type,
    first_observed_at, last_observed_at,
    from_path, to_path, cycle_id, created_at
) VALUES
    (1, 'fixture-resource-001', '/software/cloudsite-0.5.1.zip', 'observed',
     '2026-09-04 12:00:00.000000', '2026-09-04 12:00:00.000000',
     NULL, NULL, 1, '2026-09-04 12:00:00.000000');

-- User favorites (business entity: favorite)
INSERT INTO user_favorites (id, user_id, resource_id, created_at) VALUES
    (1, 1, 'fixture-resource-001', '2026-09-04 12:35:00.000000'),
    (2, 1, 'fixture-resource-002', '2026-09-04 12:36:00.000000');

-- User resource history (business entity: history)
INSERT INTO user_resource_history (
    id, user_id, resource_id, first_viewed_at, last_viewed_at,
    view_count, created_at, updated_at
) VALUES
    (1, 1, 'fixture-resource-001',
     '2026-09-04 12:35:00.000000', '2026-09-04 12:40:00.000000',
     3, '2026-09-04 12:35:00.000000', '2026-09-04 12:40:00.000000');

-- User playback progress (business entity: playback progress)
INSERT INTO user_playback_progress (
    id, user_id, resource_id, position_seconds, duration_seconds,
    completed, last_played_at, updated_at
) VALUES
    (1, 1, 'fixture-resource-002', 60, 120, 0,
     '2026-09-04 12:40:00.000000', '2026-09-04 12:40:00.000000');

-- Collections (business entity: collection/member)
INSERT INTO collections (
    id, name, description, cover, status, visible_on_home, sort_order,
    created_at, updated_at
) VALUES
    (1, 'Fixture Collection', 'A representative 0.5.1 collection', '',
     'active', 1, 0,
     '2026-09-04 12:00:00.000000', '2026-09-04 12:00:00.000000');

-- Collection items (business entity: collection/member)
INSERT INTO collection_items (
    id, collection_id, resource_id, sort_order, created_at
) VALUES
    (1, 1, 'fixture-resource-001', 0, '2026-09-04 12:05:00.000000'),
    (2, 1, 'fixture-resource-002', 1, '2026-09-04 12:06:00.000000');

-- Shares (business entity: share)
INSERT INTO shares (
    token, creator_user_id, object_type, object_id, title, enabled,
    access_mode, code_hash, code_version, expires_at, cancelled_at,
    cancel_reason, access_count, view_count, download_count,
    last_accessed_at, last_downloaded_at, created_at, updated_at
) VALUES
    ('fixture-share-token-0001', 1, 'resource', 'fixture-resource-001',
     'cloudsite-0.5.1.zip', 1, 'code', 'fixture-code-hash-0001', 1,
     '2026-09-05 12:00:00.000000', NULL, NULL,
     2, 2, 1,
     '2026-09-04 13:00:00.000000', '2026-09-04 13:05:00.000000',
     '2026-09-04 12:45:00.000000', '2026-09-04 13:05:00.000000');

-- Share verify attempts (representative, no FK to shares by schema)
INSERT INTO share_verify_attempts (
    id, share_token, ip_hash, fail_count, window_started_at,
    challenge_required_until, updated_at
) VALUES
    (1, 'fixture-share-token-0001', 'fixture-ip-hash-0001', 0,
     '2026-09-04 12:45:00.000000', NULL, '2026-09-04 12:45:00.000000');

-- Download events (representative)
INSERT INTO download_events (
    id, resource_id, result, error_code, duration_ms, source, created_at
) VALUES
    (1, 'fixture-resource-001', 'success', NULL, 250, 'public',
     '2026-09-04 13:05:00.000000');

-- Download diagnostics (representative)
INSERT INTO download_diagnostics (
    id, resource_id, status, failed_step, error_code, message,
    duration_ms, target_host, created_at
) VALUES
    (1, 'fixture-resource-001', 'ok', '', NULL, '', 250,
     'alist.fixture.example', '2026-09-04 13:05:00.000000');

-- Operation logs (representative)
INSERT INTO operation_logs (
    id, level, module, action, message, created_at
) VALUES
    (1, 'INFO', 'fixture', 'fixture_action', 'fixture message',
     '2026-09-04 12:00:00.000000');

-- Download rate limits (representative)
INSERT INTO download_rate_limits (
    id, ip_key, recent_hits_json, blocked_until, created_at, updated_at
) VALUES
    (1, 'fixture-ip-key-0001', '[]', NULL,
     '2026-09-04 12:00:00.000000', '2026-09-04 12:00:00.000000');
