#!/usr/bin/env bash
# CloudSite backup/restore content roundtrip regression test.
#
# Proves that the shipped backup, verify, and restore scripts preserve
# committed business rows and recognizable values in both state.db and
# index.db, not only SQLite quick_check integrity.  The test fails when a
# restored row is absent or a sentinel value differs, even if quick_check
# reports "ok".  A negative self-check confirms the content gate would catch
# silent value drift.
set -euo pipefail

FAIL=0
pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1" >&2; FAIL=1; }

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/cloudsite-content-roundtrip.XXXXXX")"
trap 'rm -rf -- "$WORK"' EXIT

# Sentinel values chosen to be recognizable and unlikely to appear by chance.
STATE_INSTANCE_ID="cs-rc1-roundtrip-instance-7f3c"
STATE_SITE_NAME="RoundtripBoundary"
STATE_ADMIN_USER="roundtrip-admin"
STATE_ADMIN_HASH="roundtrip-hash-placeholder"
INDEX_RESOURCE_ID="res-roundtrip-001"
INDEX_RESOURCE_NAME="roundtrip-sentinel-package.zip"
INDEX_RESOURCE_PATH="/software/roundtrip-sentinel-package.zip"
INDEX_RESOURCE_SIZE="2048"
INDEX_FOLDER_ID="folder-software"
INDEX_FOLDER_PATH="/software"

setup_fixture() {
  local root="$1"
  mkdir -p "$root/data" "$root/scripts"
  cp "$ROOT/scripts/backup.sh" "$root/scripts/backup.sh"
  cp "$ROOT/scripts/verify-backup.sh" "$root/scripts/verify-backup.sh"
  cp "$ROOT/scripts/restore.sh" "$root/scripts/restore.sh"
  printf "CLOUDSITE_SECRET_KEY=roundtrip-test-placeholder\n" > "$root/.env"
  cat > "$root/docker-compose.yml" <<'YML'
services:
  api:
    image: fake/api
YML
  python3 - "$root/data/state.db" "$root/data/index.db" \
    "$STATE_INSTANCE_ID" "$STATE_SITE_NAME" "$STATE_ADMIN_USER" "$STATE_ADMIN_HASH" \
    "$INDEX_RESOURCE_ID" "$INDEX_RESOURCE_NAME" "$INDEX_RESOURCE_PATH" "$INDEX_RESOURCE_SIZE" \
    "$INDEX_FOLDER_ID" "$INDEX_FOLDER_PATH" <<'PYFIX'
import sqlite3, sys

(state_path, index_path,
 inst_id, site_name, admin_user, admin_hash,
 res_id, res_name, res_path, res_size,
 folder_id, folder_path) = sys.argv[1:]

state = sqlite3.connect(state_path)
state.execute(
    "CREATE TABLE system_settings ("
    "key VARCHAR(100) PRIMARY KEY, value TEXT NOT NULL, "
    "value_type VARCHAR(20) DEFAULT 'string', updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
)
state.execute(
    "CREATE TABLE site_settings ("
    "id INTEGER PRIMARY KEY, site_name VARCHAR(100) NOT NULL, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
)
state.execute(
    "CREATE TABLE users ("
    "id INTEGER PRIMARY KEY, username VARCHAR(32) NOT NULL, "
    "username_normalized VARCHAR(32) NOT NULL, password_hash TEXT NOT NULL, "
    "status VARCHAR(20) DEFAULT 'active', created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
)
state.execute(
    "INSERT INTO system_settings (key, value, value_type) VALUES "
    "('instance_id', ?, 'string'), "
    "('schema_version', '3', 'integer'), "
    "('setup_completed', 'true', 'string')",
    (inst_id,),
)
state.execute(
    "INSERT INTO site_settings (id, site_name) VALUES (1, ?)",
    (site_name,),
)
state.execute(
    "INSERT INTO users (id, username, username_normalized, password_hash, status) "
    "VALUES (1, ?, ?, ?, 'active')",
    (admin_user, admin_user, admin_hash),
)
state.commit()
state.close()

index = sqlite3.connect(index_path)
index.execute(
    "CREATE TABLE resources ("
    "id VARCHAR(64) PRIMARY KEY, name VARCHAR(500) NOT NULL, "
    "path VARCHAR(1500) NOT NULL UNIQUE, parent_id VARCHAR(64), "
    "content_type VARCHAR(40), extension VARCHAR(40) DEFAULT '', "
    "size BIGINT DEFAULT 0, status VARCHAR(20) DEFAULT 'active', "
    "indexed_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
)
index.execute(
    "CREATE TABLE folders ("
    "id VARCHAR(64) PRIMARY KEY, name VARCHAR(500) NOT NULL, "
    "path VARCHAR(1500) NOT NULL UNIQUE, content_type VARCHAR(40), "
    "depth INTEGER DEFAULT 0, status VARCHAR(20) DEFAULT 'active')"
)
index.execute(
    "INSERT INTO folders (id, name, path, content_type) VALUES (?, ?, ?, 'software')",
    (folder_id, "software", folder_path),
)
index.execute(
    "INSERT INTO resources (id, name, path, parent_id, content_type, extension, size, status) "
    "VALUES (?, ?, ?, ?, 'software', 'zip', ?, 'active')",
    (res_id, res_name, res_path, folder_id, res_size),
)
index.commit()
index.close()
PYFIX
}

# assert_content <state.db> <index.db> : exits 0 only when every sentinel
# row count and value matches the expected fixtures.  Uses read-only URIs so
# a missing file or table surfaces as a hard error instead of a silent pass.
assert_content() {
  python3 - "$1" "$2" \
    "$STATE_INSTANCE_ID" "$STATE_SITE_NAME" "$STATE_ADMIN_USER" "$STATE_ADMIN_HASH" \
    "$INDEX_RESOURCE_ID" "$INDEX_RESOURCE_NAME" "$INDEX_RESOURCE_PATH" "$INDEX_RESOURCE_SIZE" \
    "$INDEX_FOLDER_ID" "$INDEX_FOLDER_PATH" <<'PYASSERT'
import sqlite3, sys

(state_path, index_path,
 exp_inst_id, exp_site_name, exp_admin_user, exp_admin_hash,
 exp_res_id, exp_res_name, exp_res_path, exp_res_size,
 exp_folder_id, exp_folder_path) = sys.argv[1:]

errors = []

def query(path, sql, params=()):
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()

for label, path in (("state.db", state_path), ("index.db", index_path)):
    ok = query(path, "PRAGMA quick_check")[0][0]
    if ok != "ok":
        errors.append(f"{label} quick_check={ok!r} (expected 'ok')")

state_settings = dict(query(
    state_path,
    "SELECT key, value FROM system_settings WHERE key IN ('instance_id','schema_version','setup_completed')",
))
if len(state_settings) != 3:
    errors.append(f"system_settings expected 3 sentinel rows, found {len(state_settings)}")
if state_settings.get("instance_id") != exp_inst_id:
    errors.append(f"system_settings.instance_id={state_settings.get('instance_id')!r} (expected {exp_inst_id!r})")
if state_settings.get("schema_version") != "3":
    errors.append(f"system_settings.schema_version={state_settings.get('schema_version')!r} (expected '3')")
if state_settings.get("setup_completed") != "true":
    errors.append(f"system_settings.setup_completed={state_settings.get('setup_completed')!r} (expected 'true')")

site_rows = query(state_path, "SELECT COUNT(*), site_name FROM site_settings WHERE id=1 GROUP BY id")
if len(site_rows) != 1:
    errors.append(f"site_settings expected 1 row for id=1, found {len(site_rows)}")
else:
    count, site_name = site_rows[0]
    if site_name != exp_site_name:
        errors.append(f"site_settings.site_name={site_name!r} (expected {exp_site_name!r})")

user_rows = query(
    state_path,
    "SELECT username, password_hash, status FROM users WHERE id=1",
)
if len(user_rows) != 1:
    errors.append(f"users expected 1 row for id=1, found {len(user_rows)}")
else:
    username, password_hash, status = user_rows[0]
    if username != exp_admin_user:
        errors.append(f"users.username={username!r} (expected {exp_admin_user!r})")
    if password_hash != exp_admin_hash:
        errors.append(f"users.password_hash={password_hash!r} (expected {exp_admin_hash!r})")
    if status != "active":
        errors.append(f"users.status={status!r} (expected 'active')")

res_rows = query(
    index_path,
    "SELECT id, name, path, parent_id, content_type, extension, size, status FROM resources",
)
if len(res_rows) != 1:
    errors.append(f"resources expected 1 row, found {len(res_rows)}")
else:
    rid, name, path, parent_id, ctype, ext, size, status = res_rows[0]
    if rid != exp_res_id:
        errors.append(f"resources.id={rid!r} (expected {exp_res_id!r})")
    if name != exp_res_name:
        errors.append(f"resources.name={name!r} (expected {exp_res_name!r})")
    if path != exp_res_path:
        errors.append(f"resources.path={path!r} (expected {exp_res_path!r})")
    if parent_id != exp_folder_id:
        errors.append(f"resources.parent_id={parent_id!r} (expected {exp_folder_id!r})")
    if ctype != "software":
        errors.append(f"resources.content_type={ctype!r} (expected 'software')")
    if ext != "zip":
        errors.append(f"resources.extension={ext!r} (expected 'zip')")
    if str(size) != str(exp_res_size):
        errors.append(f"resources.size={size!r} (expected {exp_res_size!r})")
    if status != "active":
        errors.append(f"resources.status={status!r} (expected 'active')")

folder_rows = query(
    index_path,
    "SELECT id, name, path, content_type, status FROM folders",
)
if len(folder_rows) != 1:
    errors.append(f"folders expected 1 row, found {len(folder_rows)}")
else:
    fid, name, path, ctype, status = folder_rows[0]
    if fid != exp_folder_id:
        errors.append(f"folders.id={fid!r} (expected {exp_folder_id!r})")
    if path != exp_folder_path:
        errors.append(f"folders.path={path!r} (expected {exp_folder_path!r})")
    if status != "active":
        errors.append(f"folders.status={status!r} (expected 'active')")

if errors:
    for e in errors:
        print("CONTENT MISMATCH: " + e, file=sys.stderr)
    raise SystemExit(1)
PYASSERT
}

setup_fixture "$WORK/proj"
OUT="$WORK/backup.tar.gz"

# Backup: run the shipped backup script inside the isolated project.
if (cd "$WORK/proj" && bash scripts/backup.sh "$OUT") >&2; then
  pass "backup created archive"
else
  fail "backup script failed"
fi
[[ -f "$OUT" ]] && pass "archive file present" || fail "archive file missing"

# Verify: run the shipped verify script on the archive.
if bash "$ROOT/scripts/verify-backup.sh" "$OUT" >&2; then
  pass "verify accepts archive"
else
  fail "verify rejected archive"
fi

# Restore: run the shipped restore script into a clean target directory.
RT="$WORK/restore-target"
mkdir -p "$RT"
if bash "$ROOT/scripts/restore.sh" "$OUT" --target "$RT" >&2; then
  pass "restore completed"
else
  fail "restore script failed"
fi

# Content gate: assert exact row counts and sentinel values after restore.
# This is the core RC1 evidence -- quick_check alone is not accepted.
if assert_content "$RT/data/state.db" "$RT/data/index.db" >&2; then
  pass "restored content matches sentinels"
else
  fail "restored content differs from sentinels"
fi

# Confirm the source fixture itself satisfies the content gate (sanity).
if assert_content "$WORK/proj/data/state.db" "$WORK/proj/data/index.db" >&2; then
  pass "source fixture content gate self-consistent"
else
  fail "source fixture content gate broken"
fi

# Negative self-check: build a db pair that passes quick_check but carries a
# tampered sentinel value.  The content gate MUST reject it.  This proves the
# test fails on value drift even when quick_check is ok, so a regression that
# silently swaps content cannot pass.
NEG="$WORK/negative"
mkdir -p "$NEG/data"
setup_fixture "$NEG"
python3 - "$NEG/data/state.db" <<'PYTAMPER'
import sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
conn.execute(
    "UPDATE system_settings SET value='cs-TAMPERED-should-be-caught' WHERE key='instance_id'"
)
conn.commit()
conn.close()
PYTAMPER
if assert_content "$NEG/data/state.db" "$NEG/data/index.db" >/dev/null 2>&1; then
  fail "content gate missed tampered instance_id (negative check)"
else
  pass "content gate rejects tampered value (negative check)"
fi

# Second negative check: drop the indexed resource row entirely; quick_check
# still passes but the content gate must fail on the missing row.
NEG2="$WORK/negative-missing-row"
mkdir -p "$NEG2/data"
setup_fixture "$NEG2"
python3 - "$NEG2/data/index.db" <<'PYDROP'
import sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
conn.execute("DELETE FROM resources")
conn.commit()
conn.close()
PYDROP
if assert_content "$NEG2/data/state.db" "$NEG2/data/index.db" >/dev/null 2>&1; then
  fail "content gate missed deleted resource row (negative check)"
else
  pass "content gate rejects missing resource row (negative check)"
fi

# Restore over an existing target without --force must refuse (safety gate).
mkdir -p "$WORK/occupied/data"
echo preexisting > "$WORK/occupied/.env"
if bash "$ROOT/scripts/restore.sh" "$OUT" --target "$WORK/occupied" >&2; then
  fail "restore overwrote without --force"
else
  pass "restore refuses overwrite without --force"
fi

# --- 业务关系破坏检测：verify-backup.sh 拒绝孤儿资源关系 ---
REL_STAGE="$WORK/rel-bad-stage"
mkdir -p "$REL_STAGE/data"
printf "CLOUDSITE_SECRET_KEY=rel-fixture\n" > "$REL_STAGE/.env"
python3 - "$REL_STAGE/data/state.db" "$REL_STAGE/data/index.db" <<'PYREL'
import sqlite3, sys
state, index = sys.argv[1], sys.argv[2]
c = sqlite3.connect(state)
c.execute("CREATE TABLE system_settings (key TEXT PRIMARY KEY, value TEXT)")
c.execute("INSERT INTO system_settings VALUES ('schema_version','3')")
c.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)")
c.execute("INSERT INTO users VALUES (1,'admin')")
c.commit(); c.close()
c = sqlite3.connect(index)
c.execute("CREATE TABLE folders (id TEXT PRIMARY KEY, name TEXT, path TEXT)")
c.execute("CREATE TABLE resources (id TEXT PRIMARY KEY, name TEXT, path TEXT, parent_id TEXT)")
c.execute("INSERT INTO folders VALUES ('f1','software','/software')")
c.execute("INSERT INTO resources VALUES ('r1','pkg.zip','/software/pkg.zip','nonexistent-folder')")
c.commit(); c.close()
PYREL
tar -czf "$WORK/rel-bad.tar.gz" -C "$REL_STAGE" .
if bash "$ROOT/scripts/verify-backup.sh" "$WORK/rel-bad.tar.gz" >/dev/null 2>&1; then
  fail "verify accepted orphan resource relation"
else
  pass "verify rejects orphan resource relation"
fi

# --- 验证器缺失时 verify-backup.sh 明确失败（业务归档） ---
SAFE_BIN2="$WORK/safe-bin2"
mkdir -p "$SAFE_BIN2"
for cmd in tar mktemp rm cat bash; do
  ln -sf "$(command -v "$cmd")" "$SAFE_BIN2/$cmd"
done
if (PATH="$SAFE_BIN2" bash "$ROOT/scripts/verify-backup.sh" "$OUT") >/dev/null 2>&1; then
  fail "verify should fail without verifier on business archive"
else
  pass "verify fails without verifier on business archive"
fi

if [[ "$FAIL" == "0" ]]; then
  echo "ALL TESTS PASSED"
  exit 0
else
  echo "SOME TESTS FAILED" >&2
  exit 1
fi
