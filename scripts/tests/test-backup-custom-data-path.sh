#!/usr/bin/env bash
# Regression: backup/restore honor a configured CLOUDSITE_DATA_PATH.
# Proves the default data/ stays untouched and exact DB rows round-trip
# through backup and restore when a non-default relative data path is used.
set -euo pipefail

unset CLOUDSITE_DATA_PATH

FAIL=0
pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1" >&2; FAIL=1; }

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/cloudsite-cdp-test.XXXXXX")"
trap 'rm -rf -- "$WORK"' EXIT

# ---------------------------------------------------------------------------
# Fixture: project with a non-default relative data path ./customdata.
# ---------------------------------------------------------------------------
PROJ="$WORK/proj"
mkdir -p "$PROJ/customdata" "$PROJ/scripts"
cp "$ROOT/scripts/backup.sh" "$PROJ/scripts/backup.sh"
cp "$ROOT/scripts/verify-backup.sh" "$PROJ/scripts/verify-backup.sh"
cp "$ROOT/scripts/restore.sh" "$PROJ/scripts/restore.sh"
cat > "$PROJ/.env" <<'ENV'
CLOUDSITE_SECRET_KEY=custom-path-fixture
CLOUDSITE_DATA_PATH=./customdata
ENV
cat > "$PROJ/docker-compose.yml" <<'YML'
services:
  api:
    image: fake/api
YML

# Distinctive rows so round-trip can be checked exactly.
python3 - "$PROJ/customdata/state.db" "$PROJ/customdata/index.db" <<'PYFIX'
import sqlite3, sys
state, index = sys.argv[1], sys.argv[2]
c = sqlite3.connect(state)
c.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
c.executemany("INSERT INTO users VALUES (?, ?)", [(1, "alpha"), (2, "beta"), (3, "gamma")])
c.commit(); c.close()
c = sqlite3.connect(index)
c.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, value INTEGER)")
c.executemany("INSERT INTO items VALUES (?, ?)", [(10, 100), (20, 200), (30, 300)])
c.commit(); c.close()
PYFIX

[[ ! -e "$PROJ/data" ]] && pass "default data absent before backup" || fail "default data present before backup"

# ---------------------------------------------------------------------------
# Backup must read only from ./customdata.
# ---------------------------------------------------------------------------
OUT="$WORK/backup.tar.gz"
( cd "$PROJ" && bash scripts/backup.sh "$OUT" ) >&2
[[ -f "$OUT" ]] && pass "backup archive created" || fail "backup archive not created"
[[ ! -e "$PROJ/data" ]] && pass "default data untouched after backup" || fail "backup created default data/"

# Archive keeps the portable data/ layout and does not leak the host path name.
STAGE="$WORK/inspect"
mkdir -p "$STAGE"
tar -xzf "$OUT" -C "$STAGE"
[[ -f "$STAGE/data/state.db" ]] && pass "archive has portable data/state.db" || fail "archive missing data/state.db"
[[ -f "$STAGE/data/index.db" ]] && pass "archive has portable data/index.db" || fail "archive missing data/index.db"
[[ -f "$STAGE/.env" ]] && pass "archive has .env" || fail "archive missing .env"
if tar -tzf "$OUT" | grep -q "customdata"; then
  fail "archive leaked customdata host path"
else
  pass "archive does not leak customdata host path"
fi

# ---------------------------------------------------------------------------
# Restore into a fresh target; the restored .env carries the custom path.
# ---------------------------------------------------------------------------
TGT="$WORK/target"
mkdir -p "$TGT"
bash "$ROOT/scripts/restore.sh" "$OUT" --target "$TGT" >&2
[[ -d "$TGT/customdata" ]] && pass "restore used custom data dir" || fail "restore did not use custom data dir"
[[ ! -e "$TGT/data" ]] && pass "default data untouched after restore" || fail "restore created default data/"

# Exact row round-trip.
rok=1
python3 - "$TGT/customdata/state.db" "$TGT/customdata/index.db" <<'PYCHECK' || rok=0
import sqlite3, sys
state, index = sys.argv[1], sys.argv[2]
c = sqlite3.connect(f"file:{state}?mode=ro", uri=True)
rows = c.execute("SELECT id, name FROM users ORDER BY id").fetchall()
assert rows == [(1, "alpha"), (2, "beta"), (3, "gamma")], rows
c.close()
c = sqlite3.connect(f"file:{index}?mode=ro", uri=True)
rows = c.execute("SELECT id, value FROM items ORDER BY id").fetchall()
assert rows == [(10, 100), (20, 200), (30, 300)], rows
c.close()
PYCHECK
[[ "$rok" == "1" ]] && pass "exact rows round-trip" || fail "row round-trip mismatch"

# ---------------------------------------------------------------------------
# Exported CLOUDSITE_DATA_PATH takes precedence over the .env value.
# ---------------------------------------------------------------------------
PROJ2="$WORK/proj-export"
mkdir -p "$PROJ2/hostdata" "$PROJ2/scripts"
cp "$ROOT/scripts/backup.sh" "$PROJ2/scripts/backup.sh"
cp "$ROOT/scripts/verify-backup.sh" "$PROJ2/scripts/verify-backup.sh"
cp "$ROOT/scripts/restore.sh" "$PROJ2/scripts/restore.sh"
cat > "$PROJ2/.env" <<'ENV'
CLOUDSITE_SECRET_KEY=export-precedence-fixture
CLOUDSITE_DATA_PATH=./ignored-in-env
ENV
cat > "$PROJ2/docker-compose.yml" <<'YML'
services:
  api:
    image: fake/api
YML
python3 - "$PROJ2/hostdata/state.db" "$PROJ2/hostdata/index.db" <<'PYFIX2'
import sqlite3, sys
for p in sys.argv[1:]:
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    c.execute("INSERT INTO t VALUES (42)")
    c.commit(); c.close()
PYFIX2
OUT2="$WORK/backup-export.tar.gz"
( cd "$PROJ2" && CLOUDSITE_DATA_PATH=./hostdata bash scripts/backup.sh "$OUT2" ) >&2
[[ -f "$OUT2" ]] && pass "export-precedence backup created" || fail "export-precedence backup not created"
[[ ! -e "$PROJ2/data" ]] && pass "export-precedence default data untouched" || fail "export-precedence created default data"
[[ ! -e "$PROJ2/ignored-in-env" ]] && pass "export-precedence env value ignored" || fail "export-precedence used env value"
STAGE2="$WORK/inspect-export"
mkdir -p "$STAGE2"
tar -xzf "$OUT2" -C "$STAGE2"
ek=1
python3 - "$STAGE2/data/state.db" <<'PYEC' || ek=0
import sqlite3, sys
c = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
assert c.execute("SELECT id FROM t").fetchone()[0] == 42
c.close()
PYEC
[[ "$ek" == "1" ]] && pass "export-precedence archived correct db" || fail "export-precedence archived wrong db"

# ---------------------------------------------------------------------------
# Fail closed on unsupported shell-expansion syntax in .env.
# ---------------------------------------------------------------------------
PROJ3="$WORK/proj-bad"
mkdir -p "$PROJ3/data" "$PROJ3/scripts"
cp "$ROOT/scripts/backup.sh" "$PROJ3/scripts/backup.sh"
cp "$ROOT/scripts/verify-backup.sh" "$PROJ3/scripts/verify-backup.sh"
cp "$ROOT/scripts/restore.sh" "$PROJ3/scripts/restore.sh"
cat > "$PROJ3/.env" <<'ENV'
CLOUDSITE_SECRET_KEY=bad-syntax-fixture
CLOUDSITE_DATA_PATH=${HOME}/data
ENV
cat > "$PROJ3/docker-compose.yml" <<'YML'
services:
  api:
    image: fake/api
YML
python3 - "$PROJ3/data/state.db" "$PROJ3/data/index.db" <<'PYBAD'
import sqlite3, sys
for p in sys.argv[1:]:
    c = sqlite3.connect(p); c.execute("CREATE TABLE t(id)"); c.commit(); c.close()
PYBAD
if ( cd "$PROJ3" && bash scripts/backup.sh "$WORK/should-not-exist.tar.gz" ) >&2; then
  fail "unsupported syntax should fail closed"
else
  pass "unsupported syntax fails closed"
fi
[[ ! -e "$WORK/should-not-exist.tar.gz" ]] && pass "no archive on fail-closed" || fail "archive created despite fail-closed"

# ---------------------------------------------------------------------------
# Fail closed on empty, escaping, base, and canonical-root paths.
# ---------------------------------------------------------------------------
BAD="$WORK/nested/proj-invalid"
mkdir -p "$BAD/data" "$BAD/scripts"
cp "$ROOT/scripts/backup.sh" "$BAD/scripts/backup.sh"
cp "$ROOT/scripts/verify-backup.sh" "$BAD/scripts/verify-backup.sh"
cat > "$BAD/docker-compose.yml" <<'YML'
services:
  api:
    image: fake/api
YML

assert_bad_backup_path() {
  local label="$1" value="$2" out="$3"
  printf 'CLOUDSITE_SECRET_KEY=invalid-path-fixture\nCLOUDSITE_DATA_PATH=%s\n' "$value" > "$BAD/.env"
  if ( cd "$BAD" && bash scripts/backup.sh "$out" ) >&2; then
    fail "$label should fail closed"
  else
    pass "$label fails closed"
  fi
  [[ ! -e "$out" ]] && pass "$label creates no archive" || fail "$label created an archive"
}

assert_bad_backup_path "empty data path" "" "$WORK/empty-should-not-exist.tar.gz"
assert_bad_backup_path "relative traversal" "../../escape" "$WORK/traversal-should-not-exist.tar.gz"
[[ ! -e "$WORK/escape" ]] && pass "relative traversal creates no external path" || fail "relative traversal created external path"
assert_bad_backup_path "base-directory data path" "." "$WORK/base-should-not-exist.tar.gz"

printf 'CLOUDSITE_SECRET_KEY=invalid-path-fixture\n' > "$BAD/.env"
if ( cd "$BAD" && CLOUDSITE_DATA_PATH=/tmp/.. bash scripts/backup.sh "$WORK/root-should-not-exist.tar.gz" ) >&2; then
  fail "canonical root path should fail closed"
else
  pass "canonical root path fails closed"
fi
[[ ! -e "$WORK/root-should-not-exist.tar.gz" ]] && pass "canonical root creates no archive" || fail "canonical root created an archive"

# ---------------------------------------------------------------------------
# Restore must not trust an absolute host path stored in the archive .env.
# ---------------------------------------------------------------------------
ABS_STAGE="$WORK/absolute-archive-stage"
ABS_ARCHIVE="$WORK/absolute-archive.tar.gz"
ABS_ESCAPE="$WORK/absolute-escape"
ABS_TARGET="$WORK/absolute-target"
mkdir -p "$ABS_STAGE"
cp -a "$STAGE/." "$ABS_STAGE/"
python3 - "$ABS_STAGE/.env" "$ABS_ESCAPE" <<'PYABS'
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
text = text.replace("CLOUDSITE_DATA_PATH=./customdata", f"CLOUDSITE_DATA_PATH={sys.argv[2]}", 1)
path.write_text(text, encoding="utf-8")
PYABS
tar -czf "$ABS_ARCHIVE" -C "$ABS_STAGE" .
if bash "$ROOT/scripts/restore.sh" "$ABS_ARCHIVE" --target "$ABS_TARGET" >&2; then
  fail "archived absolute restore path should fail closed"
else
  pass "archived absolute restore path fails closed"
fi
[[ ! -e "$ABS_ESCAPE" ]] && pass "archived absolute path creates no external data" || fail "archived absolute path wrote external data"
[[ ! -e "$ABS_TARGET" ]] && pass "rejected restore creates no target" || fail "rejected restore created target"

if [[ "$FAIL" == "0" ]]; then
  echo "ALL TESTS PASSED"
  exit 0
else
  echo "SOME TESTS FAILED" >&2
  exit 1
fi
