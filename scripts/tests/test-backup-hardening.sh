#!/usr/bin/env bash
# CloudSite 备份加固隔离测试。
set -euo pipefail

FAIL=0
pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1" >&2; FAIL=1; }

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/cloudsite-backup-test.XXXXXX")"
trap 'rm -rf -- "$WORK"' EXIT

setup_fixture() {
  local root="$1"
  mkdir -p "$root/data" "$root/scripts"
  cp "$ROOT/scripts/backup.sh" "$root/scripts/backup.sh"
  cp "$ROOT/scripts/verify-backup.sh" "$root/scripts/verify-backup.sh"
  cp "$ROOT/scripts/restore.sh" "$root/scripts/restore.sh"
  printf "CLOUDSITE_SECRET_KEY=test-invalid-placeholder\n" > "$root/.env"
  python3 - "$root/data/state.db" "$root/data/index.db" <<'PYFIX'
import sqlite3, sys
for path in sys.argv[1:]:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO t (id) VALUES (1)")
    conn.commit()
    conn.close()
PYFIX
  cat > "$root/docker-compose.yml" <<'YML'
services:
  api:
    image: fake/api
YML
}

setup_fixture "$WORK/proj"
OUT="$WORK/backup.tar.gz"
(cd "$WORK/proj" && bash scripts/backup.sh "$OUT") >&2
if [[ -f "$OUT" ]]; then
  perm="$(stat -c "%a" "$OUT")"
  [[ "$perm" == "600" ]] && pass "archive permission 0600" || fail "archive permission expected 600 got $perm"
else
  fail "archive not created"
fi
if ! ls -a "$WORK/proj/data" | grep -q "^\\.cloudsite-backup-"; then
  pass "no leftover temp db (normal path)"
else
  fail "leftover temp db in data/"
fi

if bash "$ROOT/scripts/verify-backup.sh" "$OUT" >&2; then
  pass "verify valid archive"
else
  fail "verify valid archive rejected"
fi

Unsafe="$WORK/unsafe.tar.gz"
python3 - "$Unsafe" <<'PYUNSAFE'
import tarfile, io, sys
with tarfile.open(sys.argv[1], "w:gz") as t:
    info = tarfile.TarInfo("../escape.txt")
    data = b"x"
    info.size = len(data)
    t.addfile(info, io.BytesIO(data))
PYUNSAFE
if bash "$ROOT/scripts/verify-backup.sh" "$Unsafe" >&2; then
  fail "unsafe path accepted"
else
  pass "unsafe path rejected"
fi

mkdir -p "$WORK/missing-stage/data"
python3 - "$WORK/missing-stage/data/state.db" <<'PYMISS'
import sqlite3, sys
c = sqlite3.connect(sys.argv[1]); c.execute("CREATE TABLE t(id)"); c.commit(); c.close()
PYMISS
tar -czf "$WORK/missing.tar.gz" -C "$WORK/missing-stage" .
if bash "$ROOT/scripts/verify-backup.sh" "$WORK/missing.tar.gz" >&2; then
  fail "missing files accepted"
else
  pass "missing files rejected"
fi

mkdir -p "$WORK/corrupt-stage/data"
printf "CLOUDSITE_SECRET_KEY=test\n" > "$WORK/corrupt-stage/.env"
python3 - "$WORK/corrupt-stage/data/state.db" "$WORK/corrupt-stage/data/index.db" <<'PYCORR'
import sqlite3, sys
for p in sys.argv[1:]:
    c = sqlite3.connect(p); c.execute("CREATE TABLE t(id)"); c.commit(); c.close()
PYCORR
printf "corrupt" > "$WORK/corrupt-stage/data/state.db"
tar -czf "$WORK/corrupt.tar.gz" -C "$WORK/corrupt-stage" .
if bash "$ROOT/scripts/verify-backup.sh" "$WORK/corrupt.tar.gz" >&2; then
  fail "corrupt db accepted"
else
  pass "corrupt db rejected"
fi

mkdir -p "$WORK/restore-target/data"
echo existing > "$WORK/restore-target/.env"
if bash "$ROOT/scripts/restore.sh" "$OUT" --target "$WORK/restore-target" >&2; then
  fail "restore overwrote without --force"
else
  pass "restore default refuses overwrite"
fi

FT="$WORK/force-target"
mkdir -p "$FT/data"
echo old-data > "$FT/data/old.txt"
echo old-env > "$FT/.env"
bash "$ROOT/scripts/restore.sh" "$OUT" --target "$FT" --force >&2
rollback_count=$(find "$FT" -maxdepth 1 -name ".restore-rollback-*" -type d | wc -l)
[[ "$rollback_count" == "1" ]] && pass "force restore one rollback" || fail "force restore rollback count $rollback_count"
rollback=$(find "$FT" -maxdepth 1 -name ".restore-rollback-*" -type d | head -1)
[[ -f "$rollback/data/old.txt" ]] && pass "rollback preserved old data" || fail "rollback missing old data"
[[ -f "$rollback/.env" ]] && pass "rollback preserved old env" || fail "rollback missing old env"
fok=1
python3 - "$FT/data/state.db" "$FT/data/index.db" <<'PYF' || fok=0
import sqlite3, sys
for p in sys.argv[1:]:
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    if c.execute("PRAGMA quick_check").fetchone()[0] != "ok":
        raise SystemExit(1)
    c.close()
PYF
[[ "$fok" == "1" ]] && pass "force restored dbs quick_check ok" || fail "force restored dbs quick_check failed"
if diff -q "$WORK/proj/.env" "$FT/.env" >/dev/null 2>&1; then
  pass "force restored .env from backup"
else
  fail "force restored .env not from backup"
fi

RT="$WORK/restore-clean"
mkdir -p "$RT"
bash "$ROOT/scripts/restore.sh" "$OUT" --target "$RT" >&2
ok=1
python3 - "$RT/data/state.db" "$RT/data/index.db" <<'PYREST' || ok=0
import sqlite3, sys
for p in sys.argv[1:]:
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    if c.execute("PRAGMA quick_check").fetchone()[0] != "ok":
        raise SystemExit(1)
    c.close()
PYREST
[[ "$ok" == "1" ]] && pass "restored dbs quick_check ok" || fail "restored dbs quick_check failed"
if diff -q "$WORK/proj/.env" "$RT/.env" >/dev/null 2>&1; then
  pass "restored .env matches fixture"
else
  fail "restored .env mismatch"
fi

setup_fixture "$WORK/proj-fail"
mkdir -p "$WORK/fake-bin"
cat > "$WORK/fake-bin/docker" <<'DOCKER'
#!/usr/bin/env bash
if [[ "$1" == "compose" && "$4" == "ps" ]]; then
  echo "fake-api-container"
  exit 0
fi
if [[ "$1" == "compose" && "$4" == "exec" ]]; then
  eval "cmd=\${$#}"
  temp_path=$(printf '%s' "$cmd" | sed -n "s#.*dst=sqlite3\.connect('\(/data/[^']*\)').*#\1#p")
  if [[ -n "$temp_path" ]]; then
    touch ".$temp_path"
    echo ".$temp_path" >> "$FAKE_DOCKER_LOG"
  fi
  exit 1
fi
exit 0
DOCKER
chmod +x "$WORK/fake-bin/docker"
FAKE_DOCKER_LOG="$WORK/fake-docker.log"
rm -f "$FAKE_DOCKER_LOG"
export FAKE_DOCKER_LOG
FAIL_OUT="$WORK/fail-backup.tar.gz"
if (cd "$WORK/proj-fail" && PATH="$WORK/fake-bin:$PATH" bash scripts/backup.sh "$FAIL_OUT") >&2; then
  fail "simulated online backup should have failed"
else
  pass "simulated online backup failed as expected"
if [[ -s "$FAKE_DOCKER_LOG" ]]; then
  pass "fake docker created temp db"
else
  fail "fake docker did not create temp db"
fi
fi
if ! ls -a "$WORK/proj-fail/data" | grep -q "^\\.cloudsite-backup-"; then
  pass "no leftover temp db (failure path)"
else
  fail "leftover temp db after failure"
fi

# --- WAL 一致性：未运行时一致性备份保留已提交 WAL 行 ---
WAL_PROJ="$WORK/wal-proj"
mkdir -p "$WAL_PROJ/data" "$WAL_PROJ/scripts"
cp "$ROOT/scripts/backup.sh" "$WAL_PROJ/scripts/backup.sh"
cp "$ROOT/scripts/verify-backup.sh" "$WAL_PROJ/scripts/verify-backup.sh"
printf "CLOUDSITE_SECRET_KEY=wal-fixture\n" > "$WAL_PROJ/.env"
cat > "$WAL_PROJ/docker-compose.yml" <<'YML'
services:
  api:
    image: fake/api
YML
python3 - "$WAL_PROJ/data/index.db" <<'PYWALIDX'
import sqlite3, sys
c = sqlite3.connect(sys.argv[1]); c.execute("CREATE TABLE t(id)"); c.execute("INSERT INTO t VALUES(1)"); c.commit(); c.close()
PYWALIDX
python3 - "$WAL_PROJ/data/state.db" <<'PYWAL'
import sqlite3, os, sys
c = sqlite3.connect(sys.argv[1])
c.execute("PRAGMA journal_mode=WAL")
c.execute("PRAGMA wal_autocheckpoint=0")
c.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
c.execute("INSERT INTO t VALUES (1)")
c.commit()
c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
c.execute("INSERT INTO t VALUES (2)")
c.commit()
os._exit(0)
PYWAL
WAL_OUT="$WORK/wal-backup.tar.gz"
if (cd "$WAL_PROJ" && bash scripts/backup.sh "$WAL_OUT") >&2; then
  if [[ -f "$WAL_OUT" ]]; then
    mkdir -p "$WORK/wal-check"
    tar -xzf "$WAL_OUT" -C "$WORK/wal-check"
    wal_count="$(python3 - "$WORK/wal-check/data/state.db" <<'PYWC'
import sqlite3, sys
c = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
print(c.execute("SELECT COUNT(*) FROM t").fetchone()[0])
c.close()
PYWC
)"
    [[ "$wal_count" == "2" ]] && pass "offline backup preserves committed WAL rows" || fail "offline backup lost WAL rows (got $wal_count)"
  else
    fail "WAL backup archive not created"
  fi
else
  fail "WAL backup script failed"
fi

# --- 验证器缺失明确失败 ---
NOTOOL_PROJ="$WORK/notool-proj"
mkdir -p "$NOTOOL_PROJ/data" "$NOTOOL_PROJ/scripts"
cp "$ROOT/scripts/backup.sh" "$NOTOOL_PROJ/scripts/backup.sh"
cp "$ROOT/scripts/verify-backup.sh" "$NOTOOL_PROJ/scripts/verify-backup.sh"
printf "CLOUDSITE_SECRET_KEY=notool-fixture\n" > "$NOTOOL_PROJ/.env"
cat > "$NOTOOL_PROJ/docker-compose.yml" <<'YML'
services:
  api:
    image: fake/api
YML
python3 - "$NOTOOL_PROJ/data/state.db" "$NOTOOL_PROJ/data/index.db" <<'PYNT'
import sqlite3, sys
for p in sys.argv[1:]:
    c = sqlite3.connect(p); c.execute("CREATE TABLE t(id)"); c.execute("INSERT INTO t VALUES(1)"); c.commit(); c.close()
PYNT
NOTOOL_OUT="$WORK/notool-backup.tar.gz"
(cd "$NOTOOL_PROJ" && bash scripts/backup.sh "$NOTOOL_OUT") >&2
SAFE_BIN="$WORK/safe-bin"
mkdir -p "$SAFE_BIN"
for cmd in tar mktemp rm cat bash; do
  ln -sf "$(command -v "$cmd")" "$SAFE_BIN/$cmd"
done
if (PATH="$SAFE_BIN" bash "$ROOT/scripts/verify-backup.sh" "$NOTOOL_OUT") >&2; then
  fail "verify should fail without any verifier"
else
  pass "verify fails without any verifier"
fi

# --- manifest 篡改检测 ---
MAN_PROJ="$WORK/man-proj"
mkdir -p "$MAN_PROJ/data" "$MAN_PROJ/scripts"
cp "$ROOT/scripts/backup.sh" "$MAN_PROJ/scripts/backup.sh"
cp "$ROOT/scripts/verify-backup.sh" "$MAN_PROJ/scripts/verify-backup.sh"
printf "CLOUDSITE_SECRET_KEY=man-fixture\n" > "$MAN_PROJ/.env"
cat > "$MAN_PROJ/docker-compose.yml" <<'YML'
services:
  api:
    image: fake/api
YML
python3 - "$MAN_PROJ/data/state.db" "$MAN_PROJ/data/index.db" <<'PYMANF'
import sqlite3, sys
for p in sys.argv[1:]:
    c = sqlite3.connect(p); c.execute("CREATE TABLE t(id)"); c.execute("INSERT INTO t VALUES(1)"); c.commit(); c.close()
PYMANF
MAN_OUT="$WORK/man-backup.tar.gz"
(cd "$MAN_PROJ" && bash scripts/backup.sh "$MAN_OUT") >&2
mkdir -p "$WORK/man-stage"
tar -xzf "$MAN_OUT" -C "$WORK/man-stage"
if [[ -f "$WORK/man-stage/manifest.json" ]]; then
  pass "backup includes manifest"
  python3 - "$WORK/man-stage/manifest.json" <<'PYTAMP'
import json, sys
p = sys.argv[1]
m = json.load(open(p))
for db in m.get("databases", {}):
    m["databases"][db]["sha256"] = "0" * 64
json.dump(m, open(p, "w"), indent=2, sort_keys=True)
PYTAMP
  tar -czf "$WORK/man-tampered.tar.gz" -C "$WORK/man-stage" .
  if bash "$ROOT/scripts/verify-backup.sh" "$WORK/man-tampered.tar.gz" >&2; then
    fail "tampered manifest checksum accepted"
  else
    pass "tampered manifest checksum rejected"
  fi
else
  fail "backup missing manifest"
fi

# --- Docker 状态未知时备份失败 ---
UNKNOWN_PROJ="$WORK/unknown-proj"
mkdir -p "$UNKNOWN_PROJ/data" "$UNKNOWN_PROJ/scripts"
cp "$ROOT/scripts/backup.sh" "$UNKNOWN_PROJ/scripts/backup.sh"
cp "$ROOT/scripts/verify-backup.sh" "$UNKNOWN_PROJ/scripts/verify-backup.sh"
printf "CLOUDSITE_SECRET_KEY=unknown-fixture\n" > "$UNKNOWN_PROJ/.env"
python3 - "$UNKNOWN_PROJ/data/state.db" "$UNKNOWN_PROJ/data/index.db" <<'PYUN'
import sqlite3, sys
for p in sys.argv[1:]:
    c = sqlite3.connect(p); c.execute("CREATE TABLE t(id)"); c.commit(); c.close()
PYUN
mkdir -p "$WORK/bad-docker-bin"
cat > "$WORK/bad-docker-bin/docker" <<'BDOCKER'
#!/usr/bin/env bash
exit 42
BDOCKER
chmod +x "$WORK/bad-docker-bin/docker"
if (cd "$UNKNOWN_PROJ" && PATH="$WORK/bad-docker-bin:$PATH" bash scripts/backup.sh "$WORK/unknown-out.tar.gz") >&2; then
  fail "backup should fail on unknown docker state"
else
  pass "backup fails on unknown docker state"
fi
[[ ! -e "$WORK/unknown-out.tar.gz" ]] && pass "unknown state creates no archive" || fail "unknown state created archive"

if [[ "$FAIL" == "0" ]]; then
  echo "ALL TESTS PASSED"
  exit 0
else
  echo "SOME TESTS FAILED" >&2
  exit 1
fi
